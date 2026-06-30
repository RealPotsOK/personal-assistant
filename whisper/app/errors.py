from __future__ import annotations


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class CapacityError(APIError):
    def __init__(self) -> None:
        super().__init__(
            "Whisper cannot acquire enough GPU capacity while other models are resident",
            503,
            "gpu_capacity_unavailable",
        )


class QueueFullError(APIError):
    def __init__(self) -> None:
        super().__init__("The Whisper inference queue is full", 429, "queue_full")


def error_body(message: str, code: str, error_type: str = "invalid_request_error") -> dict:
    return {"error": {"message": message, "type": error_type, "code": code}}
