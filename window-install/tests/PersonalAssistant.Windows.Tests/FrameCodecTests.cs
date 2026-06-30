using PersonalAssistant.Windows.Protocol;

namespace PersonalAssistant.Windows.Tests;

public sealed class FrameCodecTests
{
    [Fact]
    public void EncodesAndDecodesPa01Frame()
    {
        var encoded = FrameCodec.Encode(PayloadKind.MicPcm16, "abc"u8, 7, 42);
        var decoded = FrameCodec.Decode(encoded, 10);

        Assert.Equal(PayloadKind.MicPcm16, decoded.Kind);
        Assert.Equal((uint)7, decoded.Sequence);
        Assert.Equal((uint)42, decoded.TimestampMs);
        Assert.Equal(new byte[] { 97, 98, 99 }, decoded.Payload);
    }

    [Fact]
    public void RejectsInvalidMagic()
    {
        var encoded = FrameCodec.Encode(PayloadKind.ScreenJpeg, [], 1, 0);
        encoded[0] = 0;

        Assert.Throws<InvalidDataException>(() => FrameCodec.Decode(encoded, 10));
    }
}
