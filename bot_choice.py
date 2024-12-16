import requests
import json
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
import datetime
import os
import logging

from plugins import *
logger = logging.getLogger(__name__)

@plugins.register(
    name="BotChoice",
    desire_priority=88,
    hidden=False,
    desc="根据不同关键词调用对应任务型model或bot",
    version="0.0.1",
    author="KevinZhang",
)
class BotChoice(Plugin):

    bot_list = [
        {"url":"https://api.pearktrue.cn/api/random/xjj/", "keyword":"/sjxjj"},
        {"url": "https://api.mossia.top/randPic/pixiv", "keyword": "/sjtp"}
    ]
    max_words = 8000

    def __init__(self):
        super().__init__()
        try:
            self.config = super().load_config()
            if not self.config:
                self.config = self._load_config_template()
            self.bot_list = self.config.get("bot_list", self.bot_list)
            self.max_words = self.config.get("max_words", self.max_words)
            self.short_help_text = self.config.get("short_help_text",'发送特定指令以调度不同任务的bot！')
            self.long_help_text = self.config.get("long_help_text", "📚 发送关键词执行任务bot！/GPT/星火/随机模型等🔥 /sjxjj: 获取随机搞笑视频。\n🖼️ /sjtp: 获取随机图片。\n")  # 更新帮助信息
            logger.info(f"[BotChoice] inited, config={self.config}")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        except Exception as e:
            logger.error(f"[BotChoice] 初始化异常：{e}")
            raise "[BotChoice] init failed, ignore "

    def get_help_text(self, verbose=False, **kwargs):
        if not verbose:
            return self.short_help_text

        return self.long_help_text

    def on_handle_context(self, e_context: EventContext, retry_count: int = 0):
        context = e_context["context"]
        content = context.content

        if context.type != ContextType.TEXT:
            return

        keyword_list = [bot["keyword"] for bot in self.bot_list]
        is_return = True

        for keyword in keyword_list:
            if keyword in content:
                is_return = False
                break
        if is_return:
            return
            
        try:
            context = e_context["context"]
            msg: ChatMessage = context["msg"]
            content = context.content
            if context.type != ContextType.TEXT:
                return

            if retry_count == 0:
                logger.debug("[BotChoice] on_handle_context. content: %s" % content)
                reply = Reply(ReplyType.TEXT, "🎉请稍候...")
                channel = e_context["channel"]
                channel.send(reply, context)

            content_new = content
            for bot in self.bot_list:
                if bot["keyword"] in content:
                    url = bot["url"]
                    model = bot.get("model")  # 获取 model，如果没有则为 None
                    key = bot.get("key")  # 获取 key，如果没有则为 None

                    # 多个指令时 全部处理掉
                    for keywords in self.bot_list:
                        content_new = content_new.replace(keywords["keyword"], "")

                    # 如果是调用接口获取视频
                    if bot["keyword"] == "/sjxjj":
                        response = requests.get(url + "?type=json")
                        response.raise_for_status()
                        result = response.json()
                        video_url = result.get("video")
                        if video_url:
                            reply = Reply(ReplyType.VIDEO_URL, video_url)
                            channel = e_context["channel"]
                            channel.send(reply, context)
                        else:
                            reply = Reply(ReplyType.TEXT, "获取视频失败，请稍后再试")
                            channel = e_context["channel"]
                            channel.send(reply, context)
                    # 如果是调用接口获取图片
                    elif bot["keyword"] == "/sjtp":
                        response = requests.get(url + "?r18=1")
                        response.raise_for_status()
                        result = response.json()
                        image_url = result.get("data")
                        if image_url:
                            reply = Reply(ReplyType.IMAGE_URL, image_url)
                            channel = e_context["channel"]
                            channel.send(reply, context)
                        else:
                            reply = Reply(ReplyType.TEXT, "获取图片失败，请稍后再试")
                            channel = e_context["channel"]
                            channel.send(reply, context)

                    # 如果是调用 OpenAI 模型
                    elif model and key: 
                        openai_chat_url = url + "/chat/completions"
                        openai_headers = self._get_openai_headers(key)
                        openai_payload = self._get_openai_payload(content_new, model)
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
                        logger.debug(
                            f"[BotChoice] openai_chat_url: {openai_chat_url}, openai_headers: {openai_headers}, openai_payload: {openai_payload}")
                        response = requests.post(openai_chat_url, headers={**openai_headers, **headers},
                                                 json=openai_payload, timeout=80)
                        response.raise_for_status()
                        result = response.json()['choices'][0]['message']['content']

                        try:
                            result = json.loads(result)
                        except:
                            pass

                        if isinstance(result, list):
                            for value in result:
                                reply_type = self._get_content(value)
                                reply = Reply(reply_type, value)
                                try:
                                    channel = e_context["channel"]
                                    channel.send(reply, context)
                                except Exception as e:
                                    logger.warning(f"转存资源失败: {e}")
                                    reply = Reply(ReplyType.TEXT, value)
                                    channel.send(reply, context)
                        if isinstance(result, str):
                            reply_type = self._get_content(result)
                            reply = Reply(reply_type, result)
                            try:
                                channel = e_context["channel"]
                                channel.send(reply, context)
                            except Exception as e:
                                logger.warning(f"转存资源失败: {e}")
                                reply = Reply(ReplyType.TEXT, result)
                                channel.send(reply, context)

            e_context.action = EventAction.BREAK_PASS
            return

        except Exception as e:
            if retry_count < 3:
                logger.warning(f"[JinaSum] {str(e)}, retry {retry_count + 1}")
                self.on_handle_context(e_context, retry_count + 1)
                return

            logger.exception(f"[BotChoice] {str(e)}")
            reply = Reply(ReplyType.ERROR, "我暂时无法执行，请稍后再试")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS

    def _get_openai_headers(self, open_ai_api_key):
        return {
            'Authorization': f"Bearer {open_ai_api_key}",
            "Content-Type": "application/json"
        }

    def _get_content(self, content):
        imgs = ("jpg", "jpeg", "png", "gif", "img")
        videos = ("mp4", "avi", "mov", "pdf")
        files = ("doc", "docx", "xls", "xlsx", "zip", "rar", "txt")
        # 判断消息类型
        if content.startswith(("http://", "https://")):
            if content.lower().endswith(imgs) or self.contains_str(content, imgs):
                return ReplyType.IMAGE_URL
            elif content.lower().endswith(videos) or self.contains_str(content, videos):
                return ReplyType.VIDEO_URL
            elif content.lower().endswith(files) or self.contains_str(content, files):
                return ReplyType.FILE_URL
            else:
                logger.error("不支持的文件类型")
        return ReplyType.TEXT

    def _get_openai_payload(self, target_url_content, model):
        target_url_content = target_url_content[:self.max_words]  # 通过字符串长度简单进行截断
        messages = [{"role": "user", "content": target_url_content}]
        payload = {
            'model': model,
            'messages': messages
        }
        return payload

    def contains_str(self, content, strs):
        for s in strs:
            if s in content:
                return True
        return False

    def _load_config_template(self):
        logger.debug("No Suno plugin config.json, use plugins/bot_choice/config.json.template")
        try:
            plugin_config_path = os.path.join(self.path, "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    return plugin_conf
        except Exception as e:
            logger.exception(e)
