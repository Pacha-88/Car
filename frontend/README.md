# car-tracker frontend

React + TypeScript dashboard for browsing scraped Tesla Model Y / Model 3 listings:
price-vs-mileage scatter chart, depreciation-by-model-year module, and a filterable,
sortable, paginated listing grid. Reads a static JSON export — no backend at runtime.

## Data

The app reads `public/data/listings.json`, which is not committed (it's generated
data, gitignored). Produce it from the project root:

```bash
car-tracker export --out frontend/public/data/listings.json
```

Re-run this after every `car-tracker scrape` to refresh the dashboard.

## Develop

```bash
npm install
npm run dev
```

## Build

```bash
npm run build   # outputs to dist/
```
