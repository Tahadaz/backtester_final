# Fundamental Product Deck Assets

This folder contains the reproducible asset pipeline for `out/Module_Analyse_Fondamentale.pptx`.

## Runbook

1. Start the backing services:

   ```powershell
   docker compose -f infra/docker-compose.yml up -d quant_postgres quant_redis quant_minio quant_db_migrate
   ```

2. Seed at least four demo stocks with complete bear/base/bull valuations:

   ```powershell
   python scripts/seed_fundamental_demo.py --provider stockanalysis --symbols ATW BOA MNG IAM TQM --min-symbols 4
   ```

   If live StockAnalysis pages are unavailable, use the deterministic fixture fallback:

   ```powershell
   python scripts/seed_fundamental_demo.py --provider fixture --symbols ATW BOA MNG IAM TQM --min-symbols 4
   ```

3. Start the API and frontend:

   ```powershell
   uvicorn services.api.app.main:app --host 0.0.0.0 --port 8000
   npm --prefix frontend run dev
   ```

4. Capture dashboard screenshots:

   ```powershell
   node frontend/scripts/capture-fundamental-screens.mjs --base-url http://localhost:3000 --symbol BOA
   ```

   Screenshots are written to `docs/fundamentals-layer/assets/screens/`. The script skips missing panels with a log line and fails if fewer than six captures succeed.

5. Build the deck:

   ```powershell
   python scripts/build_fundamental_product_deck.py
   ```

   Output: `out/Module_Analyse_Fondamentale.pptx`.

## Expected Screens

- `screens/01-tearsheet.png`
- `screens/02-valuation-models.png`
- `screens/03-wacc-buildup.png`
- `screens/04-scenarios.png`
- `screens/05-sensitivity.png`
- `screens/06-scoring.png`
- `screens/07-diagnostics.png`
