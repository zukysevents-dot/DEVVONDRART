"""Konfigurace: tajné hodnoty z `.env` (pydantic-settings) + cílení z `config/targets.yaml`."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Kořen projektu = rodič složky src/ (kde leží main.py, config/, data/).
ROOT = Path(__file__).resolve().parent.parent


class Locality(BaseModel):
    """Územní cíl. `filter` je fragment AdresaFiltr pro ARES, např. {"kodObce": 582786}.

    `mestske_casti` jsou kódy `kodMestskeCastiObvodu`; klient je použije k automatickému
    zúžení, když segment (filter × NACE) přeteče strop 1000 záznamů ARES (typicky gastro
    ve velkém městě). Prázdný seznam = bez zúžení (přetékající segment se přeskočí).
    """

    name: str
    filter: dict[str, Any] = Field(default_factory=dict)
    mestske_casti: list[int] = Field(default_factory=list)


class NaceItem(BaseModel):
    code: str
    label: str


class Targets(BaseModel):
    """Obsah config/targets.yaml."""

    kraj_codes: list[int] = Field(default_factory=list)
    max_age_days: int = 30
    localities: list[Locality] = Field(default_factory=list)
    nace: list[NaceItem] = Field(default_factory=list)


class Settings(BaseSettings):
    """Tajné a runtime hodnoty z prostředí / `.env`.

    Pole pro pozdější milníky (Anthropic, SMTP) jsou volitelná, aby Milník 1
    běžel bez jakýchkoli klíčů.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Claude API (Milník 3)
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-6"

    # SMTP digest (Milník 4)
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    digest_from: Optional[str] = None
    digest_to: Optional[str] = None

    # Cesta ke konfiguraci cílení a volitelné přepsání stáří firem.
    targets_path: str = "config/targets.yaml"
    max_age_days: Optional[int] = None


def load_targets(settings: Settings | None = None) -> Targets:
    """Načte a zvaliduje targets.yaml. ENV `MAX_AGE_DAYS` má přednost před souborem."""
    settings = settings or Settings()
    path = Path(settings.targets_path)
    if not path.is_absolute():
        path = ROOT / path
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    targets = Targets(**data)
    if settings.max_age_days is not None:
        targets.max_age_days = settings.max_age_days
    return targets
