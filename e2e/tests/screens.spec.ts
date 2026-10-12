// Review screenshots of the entry dialog and results view on the dev database
// (real pilot data). Skipped unless SCREENSHOTS is set:
//   docker compose --profile e2e run --rm --no-deps -e SCREENSHOTS=1 -e E2E_BASE_URL=http://api:8000 e2e \
//     npx playwright test screens
// Files land in e2e/test-results/screens/ (not committed).
import { expect, test } from "@playwright/test";

const OUT = "test-results/screens";
const PROPERTY = "05009028972"; // Daugavpils: 1 parcel, 12 buildings, 1 premise group

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to take review screenshots");
test.use({ viewport: { width: 1440, height: 900 } });

test("review screenshots", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  const dialog = page.getByRole("dialog", { name: "Jauna pārbaude" });

  // 1. entry dialog with a property's unit list
  await dialog.getByLabel("Kadastrs", { exact: true }).fill(PROPERTY);
  await dialog.getByRole("option").filter({ hasText: "nekustamā īpašuma Nr." }).first().click();
  const list = dialog.getByTestId("unit-list");
  await expect(list.getByTestId("unit-counter")).toHaveText(/^14 no 14$/);
  await list.locator("li").nth(3).getByRole("checkbox").uncheck();
  await list.locator("li").nth(5).getByRole("checkbox").uncheck();
  await dialog.getByLabel("Projekta Nr.").fill("1.1.1.1/24/A/001");
  await page.screenshot({ path: `${OUT}/1-entry-dialog-units.png` });

  // 2. import preview
  await dialog.getByRole("button", { name: "Noņemt kadastru" }).click();
  await dialog.getByRole("tab", { name: /Importēt/ }).click();
  const csv = [
    "Kadastra Nr., apzīmējums vai adrese;Projekta Nr.;Pieteicēja reģ. Nr.",
    "5009028972;1.1.1.1/24/A/001;40003000000",
    "05009028972;1.1.1.1/24/A/001;",
    "Tautas iela 11, Daugavpils;1.1.1.1/24/A/001;",
    "09000050400;2.2.2.2/24/A/017;",
    "05000040014;2.2.2.2/24/A/017;",
    "123;2.2.2.2/24/A/017;",
    "Neesoša iela 999, Jelgava;;",
  ].join("\n");
  await dialog.getByLabel("Fails").setInputFiles({ name: "projekti.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  const preview = dialog.getByTestId("preview");
  await expect(preview.locator("tr[data-row]")).toHaveCount(7);
  await preview.getByRole("button", { name: "Noņemt rindu 3" }).click();
  await page.screenshot({ path: `${OUT}/2-import-preview.png` });

  // run it
  await dialog.getByRole("button", { name: "Pārbaudīt" }).click();
  await expect(page).toHaveURL(/[?&]run=\d+/, { timeout: 120_000 });
  await expect(page.getByTestId("designation")).toBeVisible({ timeout: 60_000 });

  // 3. results: filter bar with a pending change and the project groups
  await page.getByRole("button", { name: /Visi objekti/ }).click();
  const projects = page.getByTestId("projects");
  await expect(projects).toBeVisible();
  await projects.getByLabel("Jauna projekta Nr.").fill("3.3.3.3/24/A/005");
  await projects.getByRole("button", { name: "+ Izveidot projektu" }).click();
  await expect(projects.locator('[data-group="3.3.3.3/24/A/005"]')).toBeVisible();
  await projects.locator("tr.obj").last().getByRole("checkbox").check();
  await projects.getByLabel("Pārvietot uz projektu").selectOption({ label: "3.3.3.3/24/A/005" });
  await projects.getByRole("button", { name: /Pārvietot \(1\)/ }).click();
  await expect(projects.locator('[data-group="3.3.3.3/24/A/005"] tr.obj')).toHaveCount(1);
  await page.getByTestId("filter-bar").getByRole("button", { name: /Būvniecības lietas/ }).click();
  await expect(page.getByTestId("pending")).toBeVisible();
  await page.waitForTimeout(1500); // tiles
  await page.screenshot({ path: `${OUT}/3-results-filter-projects.png`, fullPage: true });

  // 4. Žurnāls
  await page.getByRole("button", { name: "Atjaunot" }).click();
  await expect(page.getByTestId("parent-note")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: "Žurnāls" }).click();
  await expect(page.getByTestId("journal")).toBeVisible();
  await page.screenshot({ path: `${OUT}/4-zurnals.png` });
});
