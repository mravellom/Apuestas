# ValueBet · Frontend (Arbitraje)

Next.js 15 + React 19 + TypeScript + Tailwind. Enfocado en **surebets** del backend ValueBet Engine.

## Vistas

- **/login** — login con JWT (usa `/api/v1/auth/login` del backend).
- **/arbitrage** — lista de oportunidades activas con filtros (`status`, `min_profit`),
  stats cards (activas, mejor profit, profit medio) y auto-refresh cada 60s.
- **/arbitrage/[id]** — detalle con **stake calculator interactivo**: introduce capital
  y ve cuánto apostar en cada bookmaker para el payout garantizado.

## Setup

```bash
cd frontend
cp .env.local.example .env.local   # edita NEXT_PUBLIC_API_URL si hace falta
npm install
npm run dev
```

Abre `http://localhost:3000`. Requiere el backend corriendo en `http://localhost:8000`
(configurable via `NEXT_PUBLIC_API_URL`).

## Scripts

| Comando | Qué hace |
|---------|----------|
| `npm run dev` | Servidor de desarrollo con HMR (puerto 3000) |
| `npm run build` | Build de producción |
| `npm start` | Servidor de producción |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |

## Estructura

```
app/
├── layout.tsx              Root layout (tema oscuro)
├── globals.css             Tailwind base
├── page.tsx                Redirige a /login o /arbitrage
├── login/page.tsx          Formulario de login
└── arbitrage/
    ├── page.tsx            Lista + filtros + stats
    └── [id]/page.tsx       Detalle + calculadora de stakes
components/
├── Header.tsx              Nav + logout
├── FilterBar.tsx           Controles de filtro
├── ArbitrageTable.tsx      Tabla con orden por profit
└── StakeCalculator.tsx     Input de capital → stakes y payouts
lib/
├── api.ts                  Cliente fetch con token bearer automático
├── auth.ts                 Storage del JWT en localStorage
├── types.ts                Tipos espejados del backend
└── format.ts               Helpers de formato (pct, fechas, min hasta kickoff)
```

## Stack

- **Next.js 15 App Router** (client components principalmente — simple y reactivo).
- **Tailwind 3** con paleta propia (`bg`, `surface`, `accent`…).
- Sin dependencias pesadas: sin shadcn, sin TanStack Query, sin librerías de iconos.
  La idea es que sea fácilmente extensible sin fricción.

## Auth flow

1. `POST /api/v1/auth/login` con `username` + `password` (form-data).
2. Guarda `access_token` en `localStorage` (`vb_token`).
3. `lib/api.ts` añade `Authorization: Bearer …` automáticamente en cada request.
4. Si el backend responde `401`, limpia el token y redirige a `/login`.

## Extensiones naturales

- Añadir `/opportunities` (value bets) reusando el patrón.
- Panel de `/alerts` (CRUD sobre `/api/v1/alerts/config`).
- `/performance` con gráfico de ROI / CLV (requiere Chart.js o similar).
- Server Components para prefetch inicial (proxy desde Next → backend).
- TanStack Query si el dataset crece (cache, optimistic updates).
