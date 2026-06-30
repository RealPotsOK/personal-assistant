namespace PersonalAssistant.Windows.Config;

public sealed class AppConfig
{
    public string ServerBaseUrl { get; set; } = "http://basement-server:10112";
    public string DeviceId { get; set; } = "";
    public string ProfileId { get; set; } = "";
    public string DeviceToken { get; set; } = "";
    public string? VoiceId { get; set; }
    public string Language { get; set; } = "en";
    public string Thinking { get; set; } = "medium";
    public string DeviceName { get; set; } = Environment.MachineName;
    public bool ShareAssistantProfileAcrossWindowsAccounts { get; set; }
    public int InputDeviceNumber { get; set; } = 0;
    public int OutputDeviceNumber { get; set; } = -1;
    public int? MirrorOutputDeviceNumber { get; set; }
    public int JpegQuality { get; set; } = 75;
    public int ReconnectBaseMs { get; set; } = 1000;
    public int ReconnectMaxMs { get; set; } = 15000;

    public Uri PairUri => new(new Uri(ServerBaseUrl.TrimEnd('/') + "/"), "pair");
    public Uri VoiceSetupUri => new(new Uri(ServerBaseUrl.TrimEnd('/') + "/"), "setup/voice");

    public Uri SessionUri
    {
        get
        {
            var builder = new UriBuilder(ServerBaseUrl.TrimEnd('/') + "/session")
            {
                Scheme = ServerBaseUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ? "wss" : "ws",
            };
            return builder.Uri;
        }
    }

    public void ValidateForSession()
    {
        if (string.IsNullOrWhiteSpace(ProfileId))
        {
            throw new InvalidOperationException("Missing profile_id. Run setup first.");
        }

        if (string.IsNullOrWhiteSpace(DeviceToken))
        {
            throw new InvalidOperationException("Missing device token. Run setup first.");
        }
    }
}
