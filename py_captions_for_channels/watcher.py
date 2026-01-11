import asyncio
from .channels_api import ChannelsAPI
from .parser import Parser
from .state import StateBackend
from .pipeline import Pipeline
from .channelwatch_source import ChannelWatchSource
from .config import CHANNELWATCH_URL, CHANNELS_API_URL, CAPTION_COMMAND, STATE_FILE

from .config import FAKE_MODE

async def main():
    if FAKE_MODE:
        from .mock_source import MockSource
        source = MockSource(interval_seconds=5)
    else:
        from .channelwatch_source import ChannelWatchSource
        source = ChannelWatchSource(CHANNELWATCH_URL)

    api = ChannelsAPI(CHANNELS_API_URL)
    parser = Parser()
    state = StateBackend(STATE_FILE)
    pipeline = Pipeline(CAPTION_COMMAND)

    async for partial in source.events():
        if not state.should_process(partial.timestamp):
            continue

        path = api.lookup_recording_path(partial.title, partial.start_time)
        event = parser.from_channelwatch(partial, path)

        pipeline.run(event)
        state.update(event.timestamp)
