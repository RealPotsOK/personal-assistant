namespace PersonalAssistant.Windows.Protocol;

public sealed record BinaryFrame(
    PayloadKind Kind,
    byte Flags,
    uint Sequence,
    uint TimestampMs,
    byte[] Payload);
