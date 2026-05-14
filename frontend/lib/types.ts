// Tipos del frontend.
//
// La fuente de verdad es `lib/api-types.ts` (autogenerado vía
// `npm run types:generate`). Este archivo es el bridge: re-exporta cada
// schema con el nombre que ya consumen los componentes.
//
// Si agregas un campo en un schema Pydantic, basta con regenerar — los
// tipos llegan acá sin tocar nada. Si renombras, este archivo te avisa
// con un error de TS apuntando al alias roto.

import type { components } from "./api-types";

type Schemas = components["schemas"];

// ── Arbitrajes ────────────────────────────────────────────────────────────
export type ArbitrageLeg = Schemas["ArbLegResponse"];
export type Arbitrage = Schemas["ArbResponse"];
export type ArbitrageHistoryItem = Schemas["ArbHistoryItem"];
export type ArbitrageHistoryStatus = Arbitrage["status"];
export type RevalidationResult = Schemas["RevalidationResponse"];

// ── Oportunidades (value bets) ────────────────────────────────────────────
export type OpportunityHistoryItem = Schemas["OpportunityHistoryItem"];
export type OpportunityHistoryStatus = OpportunityHistoryItem["status"];

// ── Auth ──────────────────────────────────────────────────────────────────
export type LoginResponse = Schemas["TokenResponse"];
export type CurrentUser = Schemas["UserResponse"];

// ── Paper trading ─────────────────────────────────────────────────────────
export type PaperBet = Schemas["PaperBetResponse"];
export type PaperStats = Schemas["StatsResponse"];
export type CLVBreakdown = Schemas["CLVBreakdown"];
export type PaperCLV = Schemas["CLVResponse"];

// ── Planning ──────────────────────────────────────────────────────────────
export type AllocationSuggestion = Schemas["AllocationSuggestionResponse"];
export type DailyPlan = Schemas["DailyPlanResponse"];

// ── Bankroll & ejecución ──────────────────────────────────────────────────
export type Bankroll = Schemas["BankrollResponse"];
export type LegInstruction = Schemas["LegInstructionResponse"];
export type ExecutionPlan = Schemas["ExecutionPlanResponse"];

// ── Dashboard ─────────────────────────────────────────────────────────────
export type DashboardSummary = Schemas["DashboardSummary"];
export type SportActivity = Schemas["SportActivity"];
export type LeagueArbCount = Schemas["LeagueArbCount"];
export type BookCount = Schemas["BookCount"];
export type ApiUsageSummary = Schemas["ApiUsageSummary"];
export type HourBucket = Schemas["HourBucket"];

// ── Performance / daily deployment ────────────────────────────────────────
export type DailyDeployment = Schemas["DailyDeploymentResponse"];
export type DailyDeploymentRow = Schemas["DailyDeploymentRow"];
export type DailyDeploymentSummary = Schemas["DailyDeploymentSummary"];

// ── Admin / Leagues ───────────────────────────────────────────────────────
export type AdminLeague = Schemas["app__api__v1__admin__LeagueResponse"];

// ── Bets / Tracking ───────────────────────────────────────────────────────
export type Bet = Schemas["BetResponse"];
export type BetStatus = Bet["status"];
// `result` es nullable en el schema; el tipo público es solo el valor
// posible cuando hay resultado.
export type BetResult = NonNullable<Bet["result"]>;

// ── Exposure / partial fill ───────────────────────────────────────────────
export type OutcomeScenario = Schemas["OutcomeScenarioResponse"];
export type LegSummary = Schemas["LegSummaryResponse"];
export type ReplacementOption = Schemas["ReplacementOptionResponse"];
export type ReplacementSuggestion = Schemas["ReplacementSuggestionResponse"];
export type ExposureSummary = Schemas["ExposureResponse"];
