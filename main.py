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

    KEYWORD = re.compile(
        r"#tts\s+(?:-(?P<character>\w+)\s+)?(?P<text>.+)", re.DOTALL)
    CONFIG_FILE = path.Path('Azure_config.ini')

    # 插件加载时触发
    def __init__(self, host: APIHost):
        self._config_last_mtime: float = 0.

        asyncio.run_coroutine_threadsafe(self.initialize(), host.ap.event_loop)

    # 异步初始化
    async def initialize(self):
        config = configparser.ConfigParser()

        if self.CONFIG_FILE.exists():
            config.read(self.CONFIG_FILE)
        else:
            self.ap.logger.debug(
                f'未找到Azure配置文件，正在创建默认配置，需要手动输入API_Key，必要时修改服务区域Region')

            config['DEFAULT'] = {
                'Region': 'eastus',
                'API_Key': '',
                'Speaker': 'en-US-GuyNeural',
                'Pitch': '0.00',
                'Rate': '0.00',
                'Volume': '0.00',
                'Style': 'default',
                'Styledegree': '1.0',
            }
            # 自定义角色样例
            config['neuro'] = {
                'Speaker': 'en-US-AshleyNeural',
                'Pitch': '0.28',
                'Rate': '0.05',
            }
            config.write(open(self.CONFIG_FILE, 'w'))

        self._config_last_mtime = self.CONFIG_FILE.mtime
        self.config = config

    # 具体调用Azure Service
    async def _call_api(self, text: str, *, character: str = None) -> MessageComponent:
        if character is None:
            character = 'DEFAULT'

        api_key: str = self.config[character]['API_Key']
        config_mtime: float = self.CONFIG_FILE.mtime

        # 如果api key为空（或配置文件有更新）则重新读取一遍配置
        if not api_key or config_mtime != self._config_last_mtime:
            await self.initialize()
            api_key = self.config[character]['API_Key']

        # 如果api key为空则报错
        if not api_key:
            self.ap.logger.error(f'未设置AzureTTS服务的api key！')
            return Plain("TTS配置异常！")

        speaker: str = self.config[character]['Speaker']
        pitch: float = self.config[character].getfloat('Pitch')
        rate: float = self.config[character].getfloat('Rate')
        volume: float = self.config[character].getfloat('Volume')
        style: str = self.config[character]['Style']
        styledegree: float = self.config[character].getfloat('Styledegree')
        
        headers = {
            'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm',
            'Ocp-Apim-Subscription-Key': api_key,
            'Content-Type': 'application/ssml+xml',
            'Connection': 'Keep-Alive'
        }
        data = f"""
        <speak xmlns="http://www.w3.org/2001/10/synthesis" xmlns:mstts="http://www.w3.org/2001/mstts" xmlns:emo="http://www.w3.org/2009/10/emotionml" version="1.0" xml:lang="zh-CN">
            <voice name="{speaker}">
                <mstts:express-as style="{style}" styledegree="{styledegree:+.1%}">
                    <prosody rate="{rate:+.2%}" volume="{volume:+.2%}" pitch="{pitch:+.2%}">
                        {text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>
        """.encode()
        try:
            url = f"https://{self.config[character]['Region']}.tts.speech.microsoft.com/cognitiveservices/v1"
            request = urllib.request.Request(
                url=url, headers=headers, data=data)
            response: urllib.response.addinfourl = await asyncio.to_thread(urllib.request.urlopen, request)
            if response.status != 200:
                raise urllib.error.HTTPError(
                    f"Azure状态码异常，{response.status = }")
        except urllib.error.HTTPError as he:
            self.ap.logger.error(f'AzureTTS服务调用异常，原因为{he}')
            return Plain("TTS坏掉了！")
        return Voice(base64=base64.b64encode(response.read()).decode())

    # 当收到个人或群消息时触发
    @handler(PersonNormalMessageReceived)
    @handler(GroupNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        msg = ctx.event.text_message
        if m := self.KEYWORD.match(msg):  # 如果符合关键字
            character, text = m.groupdict().values()

            if (character is not None) and (character not in self.config.sections()):
                result = f"TTS角色{repr(character)}不存在！"
            else:
                result = await self._call_api(text, character=character)

            ctx.add_return("reply", [result])

            # 阻止该事件默认行为（向接口获取回复）
            ctx.prevent_default()

    # 当回复普通消息时触发
    @handler(NormalMessageResponded)
    async def normal_message_responded(self, ctx: EventContext):
        msg = ctx.event.response_text
        target_type = ctx.event.launcher_type
        target_id = ctx.event.launcher_id
        # 强制语音发送
        await ctx.send_message(target_type, target_id, MessageChain([await self._call_api(msg)]))

    # 插件卸载时触发
    def __del__(self):
        pass
