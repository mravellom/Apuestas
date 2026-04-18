"""Interfaz base para notificadores."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationPayload:
    """Datos de una oportunidad para notificar."""

    match_home: str
    match_away: str
    commence_time: str
    market_type: str
    outcome_name: str
    bookmaker_name: str
    odds_price: float
    value_pct: float
    consensus_prob: float
    kelly_stake_pct: float | None = None

    def format_message(self) -> str:
        """Genera mensaje legible para cualquier canal."""
        value_str = f"{self.value_pct * 100:.1f}%"
        prob_str = f"{self.consensus_prob * 100:.1f}%"
        kelly_str = f"{self.kelly_stake_pct * 100:.2f}%" if self.kelly_stake_pct else "N/A"

        return (
            f"⚡ VALUE BET DETECTADA\n"
            f"\n"
            f"⚽ {self.match_home} vs {self.match_away}\n"
            f"📅 {self.commence_time}\n"
            f"🎯 {self.outcome_name} ({self.market_type})\n"
            f"🏢 {self.bookmaker_name}\n"
            f"\n"
            f"📊 Cuota: {self.odds_price:.2f}\n"
            f"📈 Value: +{value_str}\n"
            f"🎲 Prob. consenso: {prob_str}\n"
            f"💰 Kelly: {kelly_str}\n"
        )


@dataclass
class ArbitragePayload:
    """Datos de un arbitraje para notificar."""

    match_home: str
    match_away: str
    commence_time: str
    market_type: str
    profit_pct: float
    total_implied: float
    legs: list[dict]  # [{outcome_name, bookmaker, odds, stake_pct}, ...]

    def format_message(self) -> str:
        profit_str = f"{self.profit_pct:.2f}%"
        msg = (
            f"🔒 ARBITRAJE DETECTADO\n"
            f"\n"
            f"⚽ {self.match_home} vs {self.match_away}\n"
            f"📅 {self.commence_time}\n"
            f"📊 Mercado: {self.market_type}\n"
            f"💰 Ganancia garantizada: +{profit_str}\n"
            f"📉 Suma implícita: {self.total_implied:.4f}\n"
            f"\n"
            f"📋 APUESTAS:\n"
        )
        for leg in self.legs:
            pct = leg['stake_pct'] * 100
            msg += (
                f"  • {leg['outcome_name']} → {leg['bookmaker']}\n"
                f"    Cuota: {leg['odds']:.2f} | Stake: {pct:.1f}%\n"
            )
        msg += (
            f"\n"
            f"💡 Con €100: apuestas €{sum(leg['stake_pct'] * 100 for leg in self.legs):.0f}, "
            f"cobras €{100 * (1 + self.profit_pct / 100):.2f} seguro"
        )
        return msg


class Notifier(ABC):
    @abstractmethod
    async def send(self, destination: str, payload: NotificationPayload) -> bool:
        """
        Envía una notificación.

        Args:
            destination: email, chat_id, webhook URL según canal
            payload: datos de la oportunidad

        Returns:
            True si se envió correctamente
        """
        ...
