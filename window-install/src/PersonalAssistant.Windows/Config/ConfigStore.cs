using System.Security.Cryptography;
using System.Text.Json;

namespace PersonalAssistant.Windows.Config;

public sealed class ConfigStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public string UserConfigPath { get; }
    public string SharedProfilePath { get; }

    public ConfigStore()
    {
        UserConfigPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PersonalAssistant",
            "settings.json");
        SharedProfilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "PersonalAssistant",
            "machine-profile.json");
    }

    public AppConfig? Load()
    {
        if (!File.Exists(UserConfigPath))
        {
            return null;
        }

        var disk = JsonSerializer.Deserialize<DiskConfig>(File.ReadAllText(UserConfigPath), JsonOptions);
        if (disk is null)
        {
            return null;
        }

        var config = disk.ToAppConfig(Unprotect(disk.DeviceTokenProtected, DataProtectionScope.CurrentUser));
        if (disk.ShareAssistantProfileAcrossWindowsAccounts && File.Exists(SharedProfilePath))
        {
            var shared = JsonSerializer.Deserialize<SharedIdentity>(
                File.ReadAllText(SharedProfilePath),
                JsonOptions);
            if (shared is not null)
            {
                config.DeviceId = shared.DeviceId;
                config.ProfileId = shared.ProfileId;
                config.DeviceToken = Unprotect(shared.DeviceTokenProtected, DataProtectionScope.LocalMachine);
            }
        }

        return config;
    }

    public void Save(AppConfig config)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(UserConfigPath)!);
        var disk = DiskConfig.FromAppConfig(
            config,
            Protect(config.ShareAssistantProfileAcrossWindowsAccounts ? "" : config.DeviceToken, DataProtectionScope.CurrentUser));
        File.WriteAllText(UserConfigPath, JsonSerializer.Serialize(disk, JsonOptions));

        if (config.ShareAssistantProfileAcrossWindowsAccounts)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(SharedProfilePath)!);
            var shared = new SharedIdentity
            {
                DeviceId = config.DeviceId,
                ProfileId = config.ProfileId,
                DeviceTokenProtected = Protect(config.DeviceToken, DataProtectionScope.LocalMachine),
            };
            File.WriteAllText(SharedProfilePath, JsonSerializer.Serialize(shared, JsonOptions));
        }
    }

    private static string Protect(string value, DataProtectionScope scope)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "";
        }

        var bytes = ProtectedData.Protect(System.Text.Encoding.UTF8.GetBytes(value), null, scope);
        return Convert.ToBase64String(bytes);
    }

    private static string Unprotect(string protectedValue, DataProtectionScope scope)
    {
        if (string.IsNullOrWhiteSpace(protectedValue))
        {
            return "";
        }

        var bytes = ProtectedData.Unprotect(Convert.FromBase64String(protectedValue), null, scope);
        return System.Text.Encoding.UTF8.GetString(bytes);
    }

    private sealed class SharedIdentity
    {
        public string DeviceId { get; set; } = "";
        public string ProfileId { get; set; } = "";
        public string DeviceTokenProtected { get; set; } = "";
    }

    private sealed class DiskConfig
    {
        public string ServerBaseUrl { get; set; } = "http://basement-server:10112";
        public string DeviceId { get; set; } = "";
        public string ProfileId { get; set; } = "";
        public string DeviceTokenProtected { get; set; } = "";
        public string? VoiceId { get; set; }
        public string Language { get; set; } = "en";
        public string Thinking { get; set; } = "medium";
        public string DeviceName { get; set; } = Environment.MachineName;
        public bool ShareAssistantProfileAcrossWindowsAccounts { get; set; }
        public int InputDeviceNumber { get; set; }
        public int OutputDeviceNumber { get; set; } = -1;
        public int? MirrorOutputDeviceNumber { get; set; }
        public int JpegQuality { get; set; } = 75;
        public int ReconnectBaseMs { get; set; } = 1000;
        public int ReconnectMaxMs { get; set; } = 15000;

        public static DiskConfig FromAppConfig(AppConfig config, string protectedToken) => new()
        {
            ServerBaseUrl = config.ServerBaseUrl,
            DeviceId = config.DeviceId,
            ProfileId = config.ProfileId,
            DeviceTokenProtected = protectedToken,
            VoiceId = config.VoiceId,
            Language = config.Language,
            Thinking = config.Thinking,
            DeviceName = config.DeviceName,
            ShareAssistantProfileAcrossWindowsAccounts = config.ShareAssistantProfileAcrossWindowsAccounts,
            InputDeviceNumber = config.InputDeviceNumber,
            OutputDeviceNumber = config.OutputDeviceNumber,
            MirrorOutputDeviceNumber = config.MirrorOutputDeviceNumber,
            JpegQuality = config.JpegQuality,
            ReconnectBaseMs = config.ReconnectBaseMs,
            ReconnectMaxMs = config.ReconnectMaxMs,
        };

        public AppConfig ToAppConfig(string token) => new()
        {
            ServerBaseUrl = ServerBaseUrl,
            DeviceId = DeviceId,
            ProfileId = ProfileId,
            DeviceToken = token,
            VoiceId = VoiceId,
            Language = Language,
            Thinking = Thinking,
            DeviceName = DeviceName,
            ShareAssistantProfileAcrossWindowsAccounts = ShareAssistantProfileAcrossWindowsAccounts,
            InputDeviceNumber = InputDeviceNumber,
            OutputDeviceNumber = OutputDeviceNumber,
            MirrorOutputDeviceNumber = MirrorOutputDeviceNumber,
            JpegQuality = JpegQuality,
            ReconnectBaseMs = ReconnectBaseMs,
            ReconnectMaxMs = ReconnectMaxMs,
        };
    }
}
