using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using PersonalAssistant.Windows.Config;

namespace PersonalAssistant.Windows.Setup;

public sealed class PairingClient
{
    private readonly HttpClient _http = new();
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

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

    public async Task<VoiceUploadResult> UploadVoiceReferenceAsync(
        AppConfig config,
        string filePath,
        string? name,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            return VoiceUploadResult.Failed(
                "missing_voice_reference",
                "Choose an existing WAV or MP3 voice reference file.");
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
        var body = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            return FailureFromBody(response, body);
        }

        VoiceResponse? payload;
        try
        {
            payload = JsonSerializer.Deserialize<VoiceResponse>(body, JsonOptions);
        }
        catch (JsonException)
        {
            return VoiceUploadResult.Failed(
                "invalid_voice_setup_response",
                "The server returned an unreadable voice setup response.");
        }

        if (string.IsNullOrWhiteSpace(payload?.VoiceId))
        {
            return VoiceUploadResult.Failed(
                "missing_voice_id",
                "XTTS did not return a voice_id.");
        }

        return new VoiceUploadResult
        {
            VoiceId = payload.VoiceId,
            Warnings = payload.Warnings is null
                ? Array.Empty<VoiceUploadWarning>()
                : payload.Warnings,
        };
    }

    private static VoiceUploadResult FailureFromBody(HttpResponseMessage response, string body)
    {
        var code = "voice_setup_failed";
        var message = string.IsNullOrWhiteSpace(body)
            ? $"Voice setup failed with HTTP {(int)response.StatusCode}."
            : body.Trim();

        try
        {
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            if (root.ValueKind == JsonValueKind.Object)
            {
                ReadErrorObject(root, ref code, ref message);
                if (root.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
                {
                    ReadErrorObject(error, ref code, ref message);
                }
                if (root.TryGetProperty("detail", out var detail))
                {
                    if (detail.ValueKind == JsonValueKind.Object)
                    {
                        ReadErrorObject(detail, ref code, ref message);
                    }
                    else if (detail.ValueKind == JsonValueKind.String)
                    {
                        message = detail.GetString() ?? message;
                    }
                }
            }
        }
        catch (JsonException)
        {
            // Use the plain response body as the message.
        }

        return VoiceUploadResult.Failed(code, message);
    }

    private static void ReadErrorObject(JsonElement element, ref string code, ref string message)
    {
        if (element.TryGetProperty("code", out var codeElement) && codeElement.ValueKind == JsonValueKind.String)
        {
            code = codeElement.GetString() ?? code;
        }
        if (element.TryGetProperty("message", out var messageElement) && messageElement.ValueKind == JsonValueKind.String)
        {
            message = messageElement.GetString() ?? message;
        }
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

        [JsonPropertyName("warnings")]
        public List<VoiceUploadWarning>? Warnings { get; set; }
    }
}

public sealed class VoiceUploadResult
{
    public string? VoiceId { get; init; }
    public IReadOnlyList<VoiceUploadWarning> Warnings { get; init; } = Array.Empty<VoiceUploadWarning>();
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
    public bool Success => !string.IsNullOrWhiteSpace(VoiceId);

    public static VoiceUploadResult Failed(string code, string message) => new()
    {
        ErrorCode = code,
        ErrorMessage = message,
    };
}

public sealed class VoiceUploadWarning
{
    [JsonPropertyName("code")]
    public string? Code { get; init; }

    [JsonPropertyName("message")]
    public string? Message { get; init; }

    [JsonPropertyName("reference_seconds")]
    public double? ReferenceSeconds { get; init; }

    [JsonPropertyName("recommended_min_seconds")]
    public double? RecommendedMinSeconds { get; init; }

    [JsonPropertyName("recommended_max_seconds")]
    public double? RecommendedMaxSeconds { get; init; }
}
