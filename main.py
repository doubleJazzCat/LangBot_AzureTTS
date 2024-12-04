import re
import path
import base64
import asyncio
import configparser
import urllib.error
import urllib.request
import urllib.response
from pkg.plugin.events import *
from pkg.platform.types import *
from pkg.plugin.context import register, handler, BasePlugin, APIHost, EventContext


# 注册插件
@register(name="AzureTTS", description="AzureTTS service for LangBot", version="0.1", author="Ingnaryk")
class AzureTTS(BasePlugin):

    # 插件加载时触发
    def __init__(self, host: APIHost):
        config_file = path.Path('Azure_config.ini')
        config = configparser.ConfigParser()

        if config_file.exists():
            config.read(config_file)
        else:
            self.ap.logger.debug(
                f'未找到Azure配置文件，正在创建默认配置，需要手动输入API_Key，必要时修改URL')
            config['DEFAULT'] = {
                'URL': 'https://eastus.tts.speech.microsoft.com/cognitiveservices/v1',
                'API_Key': '',
                'Speaker': 'en-US-GuyNeural',
                'Pitch': '0.00',
                'Rate': '0.00',
            }
            # 自定义角色样例
            config['neuro'] = {
                'Speaker': 'en-US-AshleyNeural',
                'Pitch': '0.28',
                'Rate': '0.05',
            }
            config.write(open(config_file, 'w'))

        self.config = config
        self.keyword = re.compile(
            r"tts\s+(?:-(?P<character>\w+)\s+)?(?P<text>.+)", re.DOTALL)

    # 异步初始化
    async def initialize(self):
        pass

    # 具体调用Azure Service
    async def _call_api(self, character: str, text: str) -> MessageComponent:
        api_key: str = self.config[character]['API_Key']
        speaker: str = self.config[character]['Speaker']
        pitch: float = self.config[character]['Pitch']
        rate: float = self.config[character]['Rate']
        headers = {
            'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm',
            'Ocp-Apim-Subscription-Key': api_key,
            'Content-Type': 'application/ssml+xml',
            'Connection': 'Keep-Alive'
        }
        data = f'<speak version="1.0" xmlns="https://www.w3.org/2001/10/synthesis" xml:lang="en-US">\
            <voice name="{speaker}">\
            """<prosody pitch="{pitch:+.2%}" rate="{rate:+.2%}">"""\{text}\
            </prosody></voice></speak>'.encode()
        try:
            request = urllib.request.Request(
                self.config[character]['URL'], headers=headers, data=data)
            response: urllib.response.addinfourl = await asyncio.to_thread(urllib.request.urlopen, request)
            if response.status != 200:
                raise urllib.error.HTTPError(
                    f"Azure状态码异常，{response.status = }")
        except urllib.error.HTTPError as he:
            self.ap.logger.error(f'AzureTTS服务调用异常，原因为{he}')
            return Plain("TTS坏掉了！")
        return Voice(base64=base64.b64encode(response.content).decode())

    async def _action(self, ctx: EventContext):
        msg = ctx.event.text_message
        if m := self.keyword.match(msg):  # 如果符合关键字
            args = m.groupdict()
            character = args.get('speaker') or 'DEFAULT'

            if character != 'DEFAULT' and character not in self.config.sections():
                ctx.add_return("reply", [f"角色{repr(character)}不存在！请检查输入是否正确"])
            else:
                ctx.add_return("reply", [await self._call_api(character, args['text'])])

            # 阻止该事件默认行为（向接口获取回复）
            ctx.prevent_default()

    # 当收到个人消息时触发
    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        await self._action(ctx)

    # 当收到群消息时触发
    @handler(GroupNormalMessageReceived)
    async def group_normal_message_received(self, ctx: EventContext):
        await self._action(ctx)

    # 插件卸载时触发
    def __del__(self):
        pass
