// End-to-end tests of the entry dialog and the results view (PLAN.md §8.1, §8.2),
// run in the official Playwright container against the api-e2e service
// (synthetic seed DB, tests/batch/conftest.py):
//   docker compose --profile e2e run --rm e2e      (docs/runbook.md)
// 09000050400 lies inside the flood finding (risk high); 09000360220 is a
// property with several units; 09000360220002 is one of its buildings.
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

const runId = (page: Page) => Number(new URL(page.url()).searchParams.get("run"));

async function pickCadastre(page: Page, typed: string, designation: string, badge: string) {
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Kadastrs", { exact: true }).fill(typed);
  const option = dialog.getByRole("option").filter({ hasText: designation }).filter({ hasText: badge });
  await option.click();
}

test("search, chips, layer, Excel", async ({ page }) => {
  await noTiles(page);
  await page.goto("/");
  // the entry dialog opens by itself on first load
  const dialog = page.getByRole("dialog", { name: "Jauna pārbaude" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("sources-list")).toContainText("Plūdi");
  await expect(dialog.getByTestId("sources-list")).toContainText("daļējs pārklājums");

  await pickCadastre(page, "090000504", "09000050400", "zemes vienības apzīmējums");
  await expect(dialog.locator(".picked")).toContainText("09000050400");
  await expect(dialog.getByTestId("totals")).toHaveText(/^1 objekts · \d+ avoti$/);
  await dialog.getByRole("button", { name: "Pārbaudīt" }).click();

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

  // the URL reopens the same view, without the dialog
  await page.reload();
  await expect(page.getByTestId("designation")).toHaveText("09000050400");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("property -> untick one unit -> run -> change sources -> Atjaunot -> Žurnāls", async ({ page }) => {
  await noTiles(page);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Jauna pārbaude" });
  await pickCadastre(page, "090003602", "09000360220", "nekustamā īpašuma Nr.");

  // its units, all ticked; select all works in one click both ways
  const list = dialog.getByTestId("unit-list");
  const counter = list.getByTestId("unit-counter");
  await expect(counter).toHaveText(/^(\d+) no \1$/);
  const total = Number((await counter.textContent())!.split(" no ")[1]);
  expect(total).toBeGreaterThan(1);
  const all = list.getByLabel("Atzīmēt visu");
  await all.click();
  await expect(counter).toHaveText(`0 no ${total}`);
  await all.click();
  await expect(counter).toHaveText(`${total} no ${total}`);

  // untick one building
  await list.locator("li", { hasText: "09000360220002" }).getByRole("checkbox").uncheck();
  await expect(counter).toHaveText(`${total - 1} no ${total}`);
  await expect(all).toHaveJSProperty("indeterminate", true);
  // a property and its units are counted separately
  await expect(dialog.getByTestId("totals")).toHaveText(new RegExp(`^1 īpašums · ${total - 1} vienības · \\d+ avoti$`));
  await dialog.getByRole("button", { name: "Pārbaudīt" }).click();

  await expect(page).toHaveURL(/[?&]run=\d+/);
  await expect(page.getByTestId("designation")).toHaveText("09000360220");
  const first = runId(page);
  // only the ticked units were checked
  const stored = await (await page.request.get(`/api/runs/${first}/targets`)).json();
  const units = stored[0].units.map((u: { designation: string }) => u.designation);
  expect(units).not.toContain("09000360220002");
  expect(units.length).toBeGreaterThan(0);
  const strip = page.getByTestId("status-strip");
  await expect(strip.locator('[data-module="bis"]')).toHaveCount(1);

  // untick BIS in the filter bar: pending until Atjaunot
  const bar = page.getByTestId("filter-bar");
  await bar.getByRole("button", { name: /Būvniecības lietas/ }).click();
  await expect(page.getByTestId("pending")).toContainText("Filtru izmaiņas nav pielietotas");
  await expect(strip.locator('[data-module="bis"]')).toHaveCount(1); // not applied yet
  await bar.getByRole("button", { name: "Atjaunot" }).click();

  await expect.poll(() => runId(page)).not.toBe(first);
  const second = runId(page);
  await expect(page.getByTestId("parent-note")).toContainText(`Atjaunots no pārbaudes nr. ${first}`);
  await expect(page.getByTestId("pending")).toHaveCount(0);
  await expect(strip.locator('[data-module="bis"]')).toHaveCount(0);
  await expect(strip.locator(".chip")).toHaveCount(5);
  await expect(page.locator("#card-bis")).toHaveCount(0);
  // its layer is gone from the map panel
  await expect(page.getByTestId("layer-panel")).not.toContainText("Būvniecības lietas (BIS)");

  // Žurnāls: this server's runs are test runs (origin e2e), hidden by default;
  // with "Rādīt testa pārbaudes" both runs are listed and the old one reopens unchanged
  await page.getByRole("button", { name: "Žurnāls" }).click();
  const journal = page.getByTestId("journal");
  await expect(page.locator(".journal-filters")).toBeVisible();
  await expect(journal.locator(`tr[data-run="${second}"]`)).toHaveCount(0);
  await page.getByLabel("Rādīt testa pārbaudes").check();
  await expect(journal.locator(`tr[data-run="${second}"]`)).toContainText(`no nr. ${first}`);
  await expect(page.getByTestId("journal-range")).toContainText(/^1–\d+ no \d+$/);
  await journal.locator(`tr[data-run="${first}"]`).click();
  await expect.poll(() => runId(page)).toBe(first);
  await expect(page.getByTestId("status-strip").locator('[data-module="bis"]')).toHaveCount(1);

  // a new run on the live versions says which sources changed (none here)
  await page.getByTestId("filter-bar").getByRole("button", { name: "Pārbaudīt ar jaunākajiem datiem" }).click();
  await expect.poll(() => runId(page)).toBeGreaterThan(second);
  await expect(page.getByTestId("parent-note")).toContainText(`Pārbaudīts ar jaunākajiem datiem (no pārbaudes nr. ${first})`);
  await expect(page.getByTestId("parent-note")).toContainText("Datu versijas nav mainījušās.");
});

test("import: preview, remove a row, check", async ({ page }) => {
  await noTiles(page);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Jauna pārbaude" });
  await dialog.getByRole("tab", { name: /Importēt/ }).click();
  await expect(dialog.getByTestId("template")).toHaveAttribute("href", "/api/batch/template.xlsx");
  const csv = "vertiba;projekta_nr\n9000050400;P-1\n09000050400;P-1\n13000102702;P-2\n123;P-2\n";
  await dialog.getByLabel("Fails").setInputFiles({ name: "saraksts.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });

  const preview = dialog.getByTestId("preview");
  await expect(preview.locator("tr[data-row]")).toHaveCount(4);
  await expect(preview.locator('tr[data-row="2"]')).toContainText("Zemes vienība");
  await expect(preview.locator('tr[data-row="2"]')).toContainText("atjaunota nulle sākumā");
  await expect(preview.locator('tr[data-row="3"]')).toContainText("atkārtojas (rinda 2)");
  await expect(preview.locator('tr[data-row="5"]')).toContainText("nederīgs");
  await expect(dialog.getByTestId("totals")).toHaveText(/^3 objekti · \d+ avoti$/);

  // remove the duplicate and the invalid row
  await preview.getByRole("button", { name: "Noņemt rindu 3" }).click();
  await preview.getByRole("button", { name: "Noņemt rindu 5" }).click();
  await expect(dialog.getByTestId("totals")).toHaveText(/^2 objekti · \d+ avoti$/);
  await dialog.getByRole("button", { name: "Pārbaudīt" }).click();

  await expect(page.getByTestId("switcher")).toContainText("1 / 2");
  await expect(page.getByText(/Neatrasts \/ nav pārbaudīts/)).toHaveCount(0);
  await page.getByRole("button", { name: "Nākamais" }).click();
  await expect(page.getByTestId("designation")).toHaveText("13000102702");

  // projects: one group per project number, then a new group and a move
  await page.getByRole("button", { name: /Visi objekti/ }).click();
  const projects = page.getByTestId("projects");
  await expect(projects.locator('[data-group="P-1"] tr.obj')).toHaveCount(1);
  await expect(projects.locator('[data-group="P-2"] tr.obj')).toHaveCount(1);
  await projects.getByLabel("Jauna projekta Nr.").fill("Kopējais");
  await projects.getByRole("button", { name: "+ Izveidot projektu" }).click();
  await expect(projects.locator('[data-group="Kopējais"]')).toContainText("Nav objektu");
  await projects.getByLabel("Atzīmēt 13000102702").check();
  await projects.getByLabel("Pārvietot uz projektu").selectOption({ label: "Kopējais" });
  await projects.getByRole("button", { name: /Pārvietot \(1\)/ }).click();
  await expect(projects.locator('[data-group="Kopējais"] tr.obj')).toHaveCount(1);
  await expect(projects.locator('[data-group="P-2"]')).toContainText("Nav objektu");
  await expect(projects).toContainText(/grupējums nr\. \d+/);
  // the grouping is kept with the run
  // a project group zooms the map to its objects; "Visi projekti" fits all
  const map = page.locator(".overview-map");
  await projects.getByRole("button", { name: "Projekts Kopējais" }).click();
  await expect(map).toHaveAttribute("data-fit", "1");
  await projects.getByRole("button", { name: "Visi projekti" }).click();
  await expect(map).toHaveAttribute("data-fit", "0,1");
  const runNo = runId(page);
  // the grouping is kept with the run
  await page.reload();
  await expect(page.getByTestId("projects").locator('[data-group="Kopējais"] tr.obj')).toHaveCount(1);
  await page.getByTestId("projects").locator('[data-group="Kopējais"] tr.obj').click();
  await expect(page.getByTestId("designation")).toHaveText("13000102702");

  // Žurnāls finds the run by its (new) project name
  await page.getByRole("button", { name: "Žurnāls" }).click();
  await page.getByLabel("Rādīt testa pārbaudes").check();
  await page.getByLabel("Meklēt pēc projekta Nr.").fill("kopēj");
  const journal = page.getByTestId("journal");
  await expect(journal.locator(`tr[data-run="${runNo}"]`)).toBeVisible();
  await expect(journal.locator("tr[data-run]")).toHaveCount(1);
  await page.getByLabel("Meklēt pēc projekta Nr.").fill("nav-tāda-projekta");
  await expect(page.getByText("Atlasei neatbilst neviena pārbaude.")).toBeVisible();
});
