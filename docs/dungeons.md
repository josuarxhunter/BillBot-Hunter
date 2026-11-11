# Dungeon coverage

The catalog uses `optimalPlayerLevel` from the extracted game data, inclusive of
levels 1–50. Names below follow that source; the interface uses localized names.
Profiles cover ordinary dungeons, not guild expeditions or achievement tactics.

| ID | Level | Dungeon | Exit |
| --- | --- | --- | --- |
| 90 | 10 | Crypte de Kardorim | Kardorim |
| 8 | 20 | Grange du Tournesol Affamé | Mawy Ingalsse |
| 19 | 20 | Château Ensablé | Capitaine Igloute |
| 1 | 30 | Cour du Bouftou Royal | Rotabla le berger |
| 34 | 40 | Maison Fantôme | Gentil Organisateur Chafer |
| 45 | 40 | Donjon des Scarafeuilles | Interactive passage |
| 47 | 40 | Donjon des Squelettes | Chaferfu |
| 48 | 40 | Donjon des Tofus | Kourk Ingalsse |
| 88 | 40 | Cache de Kankreblath | Kankreblath |
| 138 | 40 | Akadémie des Gobs | Directeur Grunob |
| 13 | 50 | Donjon des Bworks | Magobwork |
| 21 | 50 | Donjon des Forgerons | Duncan |
| 25 | 50 | Grotte Hesque | Tina Montini |
| 32 | 50 | Nid du Kwakwa | Gentil Organisateur Kwakerbak |
| 33 | 50 | Donjon des Larves | Blocked: coordinated characters required |
| 36 | 50 | Donjon de Nowel | Hector Nowel |
| 142 | 50 | Refuge sylvestre | Rakoopeur |

## Access requirements

The bot prefers available keyring access, otherwise it uses a matching key from
the inventory. It rechecks access on arrival and before each dungeon in a
sequence. It does not buy keys or complete access quests.

- Kardorim: the character must have access to Incarnam. Return travel from Astrub
  is not automated by the current travel behavior.
- Skeletons: start beside Klik Klak inside the crypt. Opening the hidden cemetery
  entrance is not automated. The cemetery mechanism is described in the
  [Skeletons guide](https://www.dofuspourlesnoobs.com/donjon-des-squelettes.html).
- Kankreblath: equip the Rikiki Wand or carry the Automatic Dimensional Reducer.
  The world route permits Kerubim's shop specifically for this destination and
  evaluates the miniature passage's equipment/inventory condition. The dungeon
  key alone does not satisfy that condition.
- Hesque: access to Otomai Island and a usable route or known waypoint are required.
- Kwismas: the island must be open and reachable; the bot does not unlock it.
- Sylvan Refuge: requires access to Valonia and a known local waypoint. The boat
  journey is not automated.
- Larvae: selection, sequences and direct recovery reject this profile before
  starting. The [Larvae guide](https://www.dofuspourlesnoobs.com/donjon-des-larves.html)
  describes its split-party mechanisms. Support is intentionally deferred.

Subscriptions, server access conditions and seasonal availability still apply.

## Rooms and failure handling

The profiles specify passages for empty entry rooms, intersections, side rooms
and basements. Blacksmiths uses the short main route; the optional branch can be
left if recovery begins there. Scarafeuilles and Tofus use their designated
passages instead of attacking optional groups in transit rooms. Known fall cells
from the world graph are blocked in the approach path without changing game state.

Passage execution waits for both movement completion and the destination's full
map information. Entry and exit dialogs also wait for the corresponding map
change. Empty combat rooms and missing map transitions time out; errors stop the
sequence after bounded passage retries. Travel checks entrance reachability before
discovering or using a zaap; zaap candidates must have an onward graph route. A
failed walk does not retry the current zaap. The dungeon panel retains the result
and an actionable error when the entrance cannot be reached.

The generic combat engine plays the fights. Adding a profile does not guarantee
that a particular character can defeat the boss. Automated tests verify catalog
coverage, real key and NPC reply definitions, declared world-graph passages,
phase ordering, blocked selections and failure handling. They do not establish
successful live completion of all dungeons.

## Data and route references

The IDs, recommended levels, key definitions, NPC reply texts and passages are
checked against the repository's `DataReader`, `I18N` and `WorldGraphReader` data.
The exceptional room layouts were cross-checked with the
[Blacksmiths](https://www.dofuspourlesnoobs.com/donjon-des-forgerons.html),
[Scarafeuilles](https://www.dofuserie.com/donjons/donjon-des-scarafeuilles/) and
[Skeletons](https://www.dofuspourlesnoobs.com/donjon-des-squelettes.html) guides.


## Restarting an action

Every selected action checks the loaded character state on startup and after
reconnection. It waits for a pending map load, closes dialogs, finishes a running
fight, and leaves the haven bag before proceeding. Other actions finish a known
active dungeon before starting their own work.

The Dungeons action resumes the dungeon containing the character, including exit
and transit rooms, without requiring another entrance key. In a sequence, it
continues with the entries after that dungeon. While the bot application remains
open, pauses and game reconnects also retain the remaining entries of sequences
with repeated dungeons. After restarting the bot application itself, the current
map identifies the first matching entry in the configured sequence.
