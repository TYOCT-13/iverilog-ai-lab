"""本机 API 配置只保存密钥文件路径；按需读取，不向前端回填密钥。"""
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


def read_key_file(path: Path) -> str:
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("credential file is too large")
    key = raw.decode("utf-8-sig").strip()
    if not key or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError("credential file must contain one printable API key")
    return key


class LocalApiProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key_file: str = Field(min_length=1, max_length=2048)
    max_output_tokens: int = Field(default=4096, ge=2048, le=8192)

    @model_validator(mode="after")
    def validate_profile(self) -> "LocalApiProfile":
        parsed = urlsplit(self.endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(c.isspace() for c in self.endpoint)):
            raise ValueError("profile requires an HTTPS base URL without credentials")
        if not Path(self.api_key_file).is_absolute():
            raise ValueError("credential file path must be absolute")
        if not self.model.strip() or any(ord(c) < 32 for c in self.model):
            raise ValueError("model must be a printable identifier")
        return self

    def key_for(self, endpoint: str) -> str:
        # Changing the destination must never silently forward this profile's key.
        if endpoint.strip().rstrip("/") != self.endpoint.strip().rstrip("/"):
            return ""
        return read_key_file(Path(self.api_key_file))


def load_local_api_profile(path: Path) -> LocalApiProfile | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("API profile is too large")
    return LocalApiProfile.model_validate_json(raw)
