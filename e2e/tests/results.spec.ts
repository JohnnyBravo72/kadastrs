// Search a seed object, check it, see the module chips, switch a layer on and
// download the Excel report. The seed is tests/batch/conftest.py (synthetic
// pilot): 09000050400 lies inside the flood finding (risk high).
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

// No requests to OpenStreetMap from CI: every tile is a blank PNG.
const BLANK_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=",
  "base64",
);

async function noTiles(page: Page) {
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: BLANK_PNG }),
  );
}

test("search, chips, layer, Excel", async ({ page }) => {
  await noTiles(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Meklēt objektu" })).toBeVisible();
  await expect(page.getByTestId("template")).toHaveAttribute("href", "/api/batch/template.xlsx");

  await page.getByLabel("Meklēt").fill("090000504");
  await page.getByRole("listbox").getByText("09000050400", { exact: true }).click();
  await expect(page.locator(".chosen .tag")).toContainText("09000050400");
  await page.getByRole("button", { name: "Pārbaudīt" }).click();

  await expect(page).toHaveURL(/[?&]run=\d+/);
  await expect(page.getByTestId("designation")).toHaveText("09000050400");
  const strip = page.getByTestId("status-strip");
  await expect(strip.locator(".chip")).toHaveCount(6);
  await expect(strip.locator('[data-module="flood_10y"]')).toContainText("atrasts · risks: augsts");
  await expect(strip.locator('[data-module="address_consistency"]')).toContainText("nav piemērojams");

  // "Skatīt avotā": the object on kadastrs.lv (verified pattern, engine/links.py)
  const own = page.locator(".object-head .srclink a").first();
  await expect(own).toHaveAttribute("href", "https://www.kadastrs.lv/parcels/search?cad_num=09000050400");

  // the attention area of the flood finding is on the map
  await expect(page.locator(".leaflet-attention-pane path").first()).toBeVisible();

  // the module with a finding (flood, risk high) has its layer on by itself; the
  // clean ones (nature, BIS) are off
  await expect(page.getByLabel("Plūdi (10 gadu)", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Daba", { exact: true })).not.toBeChecked();
  await expect(page.locator(".leaflet-pludi-pane path").first()).toBeAttached();
  // chip click: its card in view
  await strip.locator('[data-module="flood_10y"]').click();
  await expect(page.locator("#card-flood_10y")).toContainText("Vismaz 10 % objekta atrodas 10 gadu plūdu zonā.");
  await expect(page.locator("#card-flood_10y .srclink a").first()).toHaveAttribute("href", /geodata\.lvgmc\.lv.*center=/);
  // a clean card is one line; the technical encumbrance is not a finding
  await expect(page.locator("#card-encumbrances")).toHaveClass(/compact/);
  await expect(page.locator("#card-encumbrances > summary")).toContainText("nav atrasts · risks: nav · 1 tehniskie");

  // a layer toggled from the panel
  const daba = page.waitForResponse((r) => r.url().includes("/layers/daba") && r.status() === 200);
  await page.getByLabel("Daba", { exact: true }).check();
  await daba;

  // the stored Excel report
  const download = page.waitForEvent("download");
  await page.getByTestId("excel").click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^kadastra_parbaude_\d+\.xlsx$/);
  const path = await file.path();
  expect(readFileSync(path).subarray(0, 2).toString()).toBe("PK"); // a zip (xlsx)

  // the URL reopens the same view
  await page.reload();
  await expect(page.getByTestId("designation")).toHaveText("09000050400");
});

test("a list: switcher and overview table", async ({ page }) => {
  await noTiles(page);
  await page.goto("/");
  await page.getByLabel("Ielīmēt sarakstu").fill("vertiba;projekta_nr\n09000050400;P-1\n13000102702;P-1\n123;P-2");
  await page.getByRole("button", { name: "Pārbaudīt" }).click();
  await expect(page.getByTestId("switcher")).toContainText("1 / 2");
  await page.getByRole("button", { name: "Nākamais" }).click();
  await expect(page.getByTestId("designation")).toHaveText("13000102702");
  await page.getByRole("button", { name: /Visi objekti/ }).click();
  const table = page.getByTestId("overview");
  await expect(table.locator("tr.obj")).toHaveCount(2);
  await expect(table).toContainText("Projekts P-1");
  await expect(page.getByText("Neatrasts / nav pārbaudīts (1)")).toBeVisible();
  await table.locator("tr.obj").first().click();
  await expect(page.getByTestId("designation")).toHaveText("09000050400");
});
