from __future__ import annotations

import abc
import logging

from models import JobPosting
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AppConfig, HospitalConfig
    from utils.http import HttpClient


class BaseAgent(abc.ABC):
    def __init__(self, hospital: "HospitalConfig", *, http: "HttpClient", logger: logging.Logger):
        self.hospital = hospital
        self.http = http
        self.logger = logger

    @abc.abstractmethod
    def scrape(self, app_config: "AppConfig") -> list[JobPosting]:
        raise NotImplementedError
