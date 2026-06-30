namespace PersonalAssistant.Windows.Protocol;

public enum PayloadKind : byte
{
    MicPcm16 = 0x01,
    ScreenJpeg = 0x02,
    ScreenPng = 0x03,
    TtsPcm16 = 0x81,
}
