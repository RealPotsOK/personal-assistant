using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using PersonalAssistant.Windows.Config;

namespace PersonalAssistant.Windows.Setup;

public sealed class PairingClient
{
    private readonly HttpClient _http = new();

    public async Task<AppConfig> PairAsync(AppConfig partialConfig, CancellationToken cancellationToken)
    {
        var response = await _http.PostAsJsonAsync(
            partialConfig.PairUri,
            new { device_name = partialConfig.DeviceName },
            cancellationToken);
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<PairResponse>(cancellationToken: cancellationToken)
            ?? throw new InvalidOperationException("Pairing response was empty.");

        partialConfig.DeviceId = payload.DeviceId;
        partialConfig.ProfileId = payload.ProfileId;
        partialConfig.DeviceToken = payload.DeviceToken;
        return partialConfig;
    }

    public async Task<string?> UploadVoiceReferenceAsync(AppConfig config, string filePath, string? name, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            return null;
        }

        using var form = new MultipartFormDataContent();
        await using var stream = File.OpenRead(filePath);
        using var file = new StreamContent(stream);
        file.Headers.ContentType = new MediaTypeHeaderValue(
            Path.GetExtension(filePath).Equals(".mp3", StringComparison.OrdinalIgnoreCase)
                ? "audio/mpeg"
                : "audio/wav");
        form.Add(file, "reference_audio", Path.GetFileName(filePath));
        form.Add(new StringContent(name ?? config.DeviceName), "name");

        using var request = new HttpRequestMessage(HttpMethod.Post, config.VoiceSetupUri);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", config.DeviceToken);
        request.Content = form;
        var response = await _http.SendAsync(request, cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return null;
        }

        var payload = await response.Content.ReadFromJsonAsync<VoiceResponse>(cancellationToken: cancellationToken);
        return payload?.VoiceId;
    }

    private sealed class PairResponse
    {
        [JsonPropertyName("device_id")]
        public string DeviceId { get; set; } = "";

        [JsonPropertyName("profile_id")]
        public string ProfileId { get; set; } = "";

        [JsonPropertyName("device_token")]
        public string DeviceToken { get; set; } = "";
    }

    private sealed class VoiceResponse
    {
        [JsonPropertyName("voice_id")]
        public string? VoiceId { get; set; }
    }
}
