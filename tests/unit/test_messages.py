from struct import pack
from unittest import TestCase, mock

from vncdotool import messages
from vncdotool.const import FenceFlags, MsgS2C
from vncdotool.decoders import DecodeError


def drive(handler, client, *blocks):
    """Send a handler's generator each block in turn, like the pump would."""
    generator = handler.handle(client)
    block = None
    for block in (None, *blocks):
        try:
            generator.send(block)
        except StopIteration:
            return
    raise AssertionError("handler did not finish after the given blocks")


class TestHandlerRegistry(TestCase):

    def test_registry_keys_match_their_own_class(self):
        for message, cls in messages.HANDLERS.items():
            assert cls.MESSAGE == message

    def test_for_connection_builds_one_instance_per_message(self):
        instances = messages.for_connection()
        assert set(instances) == set(messages.HANDLERS)
        for message, handler in instances.items():
            assert isinstance(handler, messages.HANDLERS[message])


class TestBellHandler(TestCase):

    def test_bell(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.BELL]()
        drive(handler, client)
        client.bell.assert_called_once_with()


class TestSetColourMapEntriesHandler(TestCase):

    def test_set_color_map(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SET_COLOUR_MAP_ENTRIES]()
        colors = [(1, 2, 3), (0xFFFF, 0, 0x1234)]
        payload = pack("!xHH", 5, len(colors)) + b"".join(
            pack("!HHH", *color) for color in colors
        )
        drive(handler, client, payload[:5], payload[5:])
        client.requirePayload.assert_called_once_with(6 * len(colors))
        client.set_color_map.assert_called_once_with(5, colors)

    def test_oversized_colour_count_is_bounded(self):
        client = mock.Mock()
        client.requirePayload.side_effect = DecodeError("too big")
        handler = messages.HANDLERS[MsgS2C.SET_COLOUR_MAP_ENTRIES]()
        generator = handler.handle(client)
        generator.send(None)
        with self.assertRaises(DecodeError):
            generator.send(pack("!xHH", 0, 0xFFFF))


class TestServerCutTextHandler(TestCase):

    def test_copy_text(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SERVER_CUT_TEXT]()
        text = "hello"
        data = text.encode("iso-8859-1")
        drive(handler, client, pack("!xxxI", len(data)), data)
        client.requirePayload.assert_called_once_with(len(data))
        client.copy_text.assert_called_once_with(text)

    def test_oversized_length_is_bounded_before_reading_the_payload(self):
        client = mock.Mock()
        client.requirePayload.side_effect = DecodeError("too big")
        handler = messages.HANDLERS[MsgS2C.SERVER_CUT_TEXT]()
        generator = handler.handle(client)
        generator.send(None)
        with self.assertRaises(DecodeError):
            generator.send(pack("!xxxI", 1 << 30))
        client.copy_text.assert_not_called()


class TestServerFenceHandler(TestCase):

    def test_request_gets_a_response_with_request_cleared(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SERVER_FENCE]()
        flags = FenceFlags.REQUEST | FenceFlags.BLOCK_AFTER | FenceFlags.BLOCK_BEFORE
        drive(handler, client, pack("!xxxIB", flags, 0))
        client.clientFence.assert_called_once_with(
            FenceFlags.BLOCK_AFTER | FenceFlags.BLOCK_BEFORE, b""
        )

    def test_clears_bits_the_client_does_not_understand(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SERVER_FENCE]()
        flags = FenceFlags.REQUEST | 0x08  # an unknown bit
        drive(handler, client, pack("!xxxIB", flags, 0))
        client.clientFence.assert_called_once_with(FenceFlags(0), b"")

    def test_response_is_not_echoed_back(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SERVER_FENCE]()
        flags = FenceFlags.BLOCK_AFTER | FenceFlags.BLOCK_BEFORE  # no REQUEST
        drive(handler, client, pack("!xxxIB", flags, 0))
        client.clientFence.assert_not_called()

    def test_payload_is_echoed_back_with_the_response(self):
        client = mock.Mock()
        handler = messages.HANDLERS[MsgS2C.SERVER_FENCE]()
        drive(handler, client, pack("!xxxIB", FenceFlags.REQUEST, 4), b"ping")
        client.clientFence.assert_called_once_with(FenceFlags(0), b"ping")
