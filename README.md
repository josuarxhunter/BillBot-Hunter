## Bot Dofus Unity ( Dofus 3 ) : Farming / Fight / HDV / Craft

Windows bot for Dofus Unity with harvesting, combat, crafting, multiple accounts,
and session scheduling. Built with Python, PyQt6, and FluentWidgets.

[Download for Windows](https://github.com/Valentin-alix/BillBot/releases/latest)

![Bill running alongside Dofus Unity](./resources/screenshots/bot.gif)

## Features

- Harvesting, automatic combat, crafting, and marketplace sales.
- Character, inventory, bank, map, and route monitoring.
- Account schedules, email accounts, and proxy management.
- Activity logs, quarantined item controls, and protocol inspection.
- **Socket** mode: connects directly to the game servers without the game client.
- **MITM** mode: intercepts traffic between the Dofus Unity client and the servers.

## Getting started

### Download

Extract the Windows archive from the [latest release](https://github.com/Valentin-alix/BillBot/releases/latest)
and run `BillBot.exe`.

If Microsoft Defender quarantines `BillBot.exe`, add an exclusion for a dedicated
BillBot installation folder before extracting the archive again:

1. Create the installation folder, for example `C:\BillBot`.
2. Open **Windows Security → Virus & threat protection → Manage settings →
   Exclusions → Add or remove exclusions → Add an exclusion → Folder** and select it.
3. Extract the release ZIP into that folder and run `BillBot.exe`.

Only do this for a release you trust: Defender's real-time scanning will exclude
that folder. Keep the exclusion limited to BillBot's folder; do not exclude all
Downloads or disable antivirus protection.
[Microsoft's exclusion instructions](https://support.microsoft.com/en-gb/windows/security/threat-malware-protection/virus-and-threat-protection-in-the-windows-security-app).

### From source

Requirements: **Windows**, **Python 3.12**, **Git LFS**, and **uv**.
Clone the repository and run these commands from its root in PowerShell:

```powershell
git lfs install
git lfs pull
uv sync
uv run playwright install chromium
Copy-Item .env.example .env
uv run python __main__.py
```

Copy `.env.example` only on first installation; keep any existing `.env`.
MITM mode requires Dofus Unity installed through the Ankama launcher.
Cytrus is optional and handles automatic updates.

### Configuration

In **Settings**, choose behaviors, define schedules, and assign accounts to profiles.
Start an activity from the account controls and use **Activity** to review errors.
Behavior changes apply on the next bot start; account automation settings apply
at the next operation.

For **Configurable automatic**, open the account's **Parameters** tab (also
available without debug mode). Preferences are saved separately for each account
and apply on the next start. Choose balanced harvesting, kamas, profession
progression, or selected resources. A resource quantity of zero means unlimited;
other targets include the last known bank stock and current inventory.

For **Dungeons**, the **Parameters** tab lets you select a supported dungeon or
enable an ordered sequence. Add dungeons to the list and move them up or down;
the sequence runs once and stops on an error or if neither a key nor keyring access
is available. The bot prefers the keyring and otherwise consumes a matching key
from the inventory. Preferences are saved per account and also apply to dungeon
activities in scheduled automatic sessions. The selector covers all 17 dungeons
with recommended levels 1–50 in the extracted catalog; 16 have execution profiles.
Larvae remains visible but blocked until coordinated multi-character mechanisms
are implemented. Special access requirements appear in the panel. See
[dungeon coverage and access requirements](docs/dungeons.md) before starting.

The tab groups zone rotation and productivity limits, transport budgets, combat,
and resource targets. Zone selection filters harvesting requirements, compares
accessible routes and estimated travel costs, and keeps productive zones unless
the improvement justifies moving. Zaap prices are checked against the live quote
before spending the protected reserve. Failed zones can become eligible again
after a cooldown. Recovery combat is optional and limited in time.

Travel times, resource values and profession progression scores are estimates,
not measured kamas/hour or exact profession XP. Missing or old prices receive
less confidence. The activity panel explains the selected zone, priority
resources and travel budget, and reports recent harvesting productivity.

## Development

- `src/`: bot and interface.
- `AnkamaLauncherEmulator/`: interactions with Ankama services.
- `DBDofusUnity/`: protocol mapper and Unity game-data reader.
- `scripts/`: packaging, launcher, maintenance, mapping, and data tools.

Run tools from the repository root. The **Debug** view provides message inspection
and searchable logs; start the standalone sniffer with
`uv run python -m scripts.mapping.sniffer`.
Each new Dofus build requires regenerating and verifying the protocol mapping.

### Build data tools

Before using the Unity static-data tools, install **.NET 10** and
**Visual Studio C++ build tools (v145)**, then run from the repository root
in **Git Bash on Windows**:

```bash
bash scripts/packaging/build-tools.sh
```

This builds UABEA, Il2CppInspector, and protodec.

### Checks

```powershell
uv run ruff check .
uv run pyright
uv run pytest tests
```

Run `uv run poe verify` for the final check; it also applies Ruff fixes.
