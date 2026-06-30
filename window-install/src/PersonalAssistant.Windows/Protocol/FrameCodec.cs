using System.Buffers.Binary;

namespace PersonalAssistant.Windows.Protocol;

public static class FrameCodec
{
    public const int HeaderSize = 16;
    private static readonly byte[] Magic = "PA01"u8.ToArray();

    public static byte[] Encode(PayloadKind kind, ReadOnlySpan<byte> payload, uint sequence, uint timestampMs, byte flags = 0)
    {
        var output = new byte[HeaderSize + payload.Length];
        Magic.CopyTo(output, 0);
        output[4] = (byte)kind;
        output[5] = flags;
        output[6] = 0;
        output[7] = 0;
        BinaryPrimitives.WriteUInt32BigEndian(output.AsSpan(8, 4), sequence);
        BinaryPrimitives.WriteUInt32BigEndian(output.AsSpan(12, 4), timestampMs);
        payload.CopyTo(output.AsSpan(HeaderSize));
        return output;
    }

    public static BinaryFrame Decode(ReadOnlySpan<byte> frame, int maxPayloadBytes)
    {
        if (frame.Length < HeaderSize)
        {
            throw new InvalidDataException("Frame is shorter than the 16-byte PA01 header.");
        }

        if (!frame[..4].SequenceEqual(Magic))
        {
            throw new InvalidDataException("Invalid PA01 frame magic.");
        }

        if (frame[6] != 0 || frame[7] != 0)
        {
            throw new InvalidDataException("Reserved PA01 header bytes must be zero.");
        }

        var payloadLength = frame.Length - HeaderSize;
        if (payloadLength > maxPayloadBytes)
        {
            throw new InvalidDataException("PA01 payload exceeds the configured limit.");
        }

        var payload = frame[HeaderSize..].ToArray();
        return new BinaryFrame(
            (PayloadKind)frame[4],
            frame[5],
            BinaryPrimitives.ReadUInt32BigEndian(frame.Slice(8, 4)),
            BinaryPrimitives.ReadUInt32BigEndian(frame.Slice(12, 4)),
            payload);
    }
}
