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

## Confirmed operation

The user has confirmed full operation only for Hungry Sunflower, Royal Gobball,
Sandcastle, and Ghost House. Other profiles remain pending full live validation.
A dungeon finish event after a manual entry or resumed run does not establish
that the entire entrance and room traversal are automated.

Kankreblath's wall-hole interaction exists. A recorded equipment-field mapping
error left the bot with stale weapon positions, and the failed gate remained
banned even after re-equipping the Rikiki Wand (varita Pituza). Equipment messages
now preserve the actual item UID and position; moving that access item also
invalidates its previous gate ban so the route can be retried.

## Access requirements

The bot prefers available keyring access, otherwise it uses a matching key from
the inventory. It rechecks access on arrival and before each dungeon in a
sequence. It does not buy keys or complete access quests.

- Kardorim: the character must have access to Incarnam. Return travel from Astrub
  is not automated by the current travel behavior.
- Skeletons: travel to cemetery map `82314497` (`[10,15]`), step on plate `99`,
  wait for the server to open the tomb, then walk to `259` and wait for crypt
  map `87032320` before talking to Klik Klak. If already on the plate, step to
  `114` and back to reactivate it. The passage starts immediately after opening
  to respect the approximately ten-second window. The mechanism is described in the
  [Skeletons guide](https://www.dofuspourlesnoobs.com/donjon-des-squelettes.html).
  Chaferfu's exit dialog starts with "Demander son secret", then asks to leave
  and ends with "Dire bonjour" (recorded replies `65566 -> 65568 -> 65570`).
- Kankreblath: equip the Rikiki Wand or carry the Automatic Dimensional Reducer.
  The world route permits Kerubim's shop specifically for this destination and
  evaluates the miniature passage's equipment/inventory condition. The dungeon
  key alone does not satisfy that condition.
  While inside its rooms or exit room, post-fight inventory upgrades preserve
  the weapon slot if the Rikiki Wand (`15990`) is equipped, so repeated entries
  in a sequence retain access. Other equipment slots can still improve.
  This protection does not equip a wand that is already in the backpack; equip
  it once before resuming if a previous run replaced it. Outside the dungeon,
  ordinary automatic weapon upgrades remain available.
- Hesque: the Otomai access quests must already be completed. If no route or
  known waypoint reaches the entrance, travel to Captain Kradoc at `[12,29]`
  (map `95424516`) and request the return trip to Otomai. Quest acceptance,
  resource delivery and the first shipwreck journey are not automated.
- Kwismas: the island must be open. If no direct route exists, travel to Hector
  at `[8,-6]` (map `68420097`) and use the declared island travel replies. Missing
  seasonal NPCs or unavailable boarding options stop the action.
- Sylvan Refuge: prefer a reachable Valonia waypoint; otherwise travel to Captain
  Isabello Tissier at `[10,-3]` (map `68421124`) and pay 100 kamas to board.
  The fare is checked before traveling and again before opening the dialog.
- Larvae: selection, sequences and direct recovery reject this profile before
  starting. The [Larvae guide](https://www.dofuspourlesnoobs.com/donjon-des-larves.html)
  describes its split-party mechanisms. Support is intentionally deferred.

Subscriptions, server access conditions and seasonal availability still apply.

## Pending profile audit

| Dungeon | Local audit / implementation | Remaining evidence |
| --- | --- | --- |
| Skeletons | Plate 99 activation and dynamic tomb opening added; key and keyring replies verified | Live timed crypt entry and a complete run |
| Tofus | Farm entrance interaction exists in the graph; introductory NPC reply added; user-marked holes blocked and green route declared | Complete live run and any additional holes |
| Gob Academy | Key, keyring and exit replies verified; side-room return declared | Complete live run |
| Bworks | Key, keyring and exit replies verified; full user-marked hole footprint blocked; basement return declared | Complete live run and any additional holes |
| Blacksmiths | Replies verified; main route and optional-room recovery declared; branch triggers blocked | Complete live run |
| Hesque | Replies verified; Kradoc return boat added when no direct route exists | Completed access quests and live boarding/run |
| Kwakwa | Entrance/exit replies verified; cave entrance interaction exists in the graph | Complete live run |
| Kwismas | Replies verified; Hector boarding added when no direct route exists | Open island and live boarding/run |
| Sylvan Refuge | Replies verified; 100-kama Valonia boat added when no direct route exists | Live boarding/run |

## Rooms and failure handling

The profiles specify passages for empty entry rooms, intersections, side rooms
and basements. Blacksmiths uses the short main route; the optional branch can be
left if recovery begins there. Scarafeuilles and Tofus use their designated
passages instead of attacking optional groups in transit rooms. Known fall cells
from the world graph are blocked in the approach path without changing game state.

The map movement provider also rejects known fall cells for every movement
outside combat, including interactive retries and approaches to monster groups:
Scarafeuilles `94111744`: `384`, `441`, `429`; Tofus `96206850`:
`261`, `288`, `330`, `367`, `371`, `381`, `385`, `423`, `466`;
Bworks `104599041`: `328`, `329`, `342`, `343`, `344`, `355`, `356`, `357`,
`358`, `369`, `370`, `371`, `372`, `383`, `384`, `385`, `386`, `397`, `398`,
`399`, `400`, `411`, `412`, `413`, `426`, `427`. These are the walkable cells
of linked zone `16`, containing both graph trigger `372` and recorded fall `386`.
Bworks uses perimeter routes as ordered waypoints, joining at the nearest
waypoint instead of walking back to the start of a branch:
`395 -> 381 -> 367 -> 353 -> 340 -> 326 -> 313 -> 299 -> 300 -> 287 -> 301 -> 316`
or `456 -> 442 -> 429 -> 415 -> 401 -> 387 -> 374 -> 359 -> 345 -> 330 -> 316`.
Each segment waits for arrival and refuses detours; from `316` it uses the door.
The session `20261112T163626_953963-0500` records `401 -> 386` at `16:37:25`
followed by a fall into `104599043`; at `16:38:32`, resuming at `367` repeatedly
refused the non-straight segment to `354`. The corrected routes avoid `386` and
use contiguous segments. Planner tests cover starts `396`, `470`, `367`, `402`
and all 26 linked-zone hole cells. A movement completion during map loading now
waits for full map information before accessing the cleared player actor.
The user confirmed the corrected Bworks crossing on 2026-11-12. This does not
establish full entrance-to-exit automation for the whole dungeon.
Combat walkability and extracted map files are unchanged.
Blacksmiths also blocks the unwanted branch triggers at `87297537:174` and
`87296517:178` while retaining recovery routes from those optional rooms.
The graph establishes only one fall cell per trap room; it does not establish
that all server-triggered holes have been enumerated.

For Tofus room two (`96206850`, `[5,6]`), the user's annotated image supplies
the nine yellow hole cells above and the green route
`452 -> 396 -> 301 -> 273 -> 260 -> 289 -> 262`, followed by the door at `248`.
Each waypoint waits for confirmed arrival; detours away from its straight segment
are refused. Tests use the actual map geometry and planner, including resuming
from `301`. The colored red markers have no supplied meaning and are not treated
as additional holes. The marked route still needs a successful live crossing.

Island transport waits for both dialog completion and full destination map data
before resuming travel to the entrance. Only one boarding attempt per dungeon
start is allowed. A failed onward route stops instead of returning to the boat.
Tofus also accepts Kourk's introductory "Continuer la discussion" reply before
the key or keyring choices.

Passage execution waits for both movement completion and the destination's full
map information. Entry and exit dialogs also wait for the corresponding map
change. Empty combat rooms and missing map transitions time out; errors stop the
sequence after bounded passage retries. Travel checks entrance reachability before
discovering or using a zaap; zaap candidates must have an onward graph route. A
failed walk does not retry the current zaap. The dungeon panel retains the result
and an actionable error when the entrance cannot be reached.
Zaap discovery and selection cap the coordinate-distance estimate by the actual
walking route length when that route exists. In Kankreblath, exit `103549440`
and entrance `146676736` share `[3,-17]` across different subareas; the old
coordinate heuristic assigned a distance of ten and caused an unnecessary
Astrub zaap round trip between repeated runs. Tests cover direct return both
with the local zaap known and with it undiscovered.

The generic combat engine plays the fights. Adding a profile does not guarantee
that a particular character can defeat the boss. Automated tests verify catalog
coverage, real key and NPC reply definitions, declared world-graph passages,
phase ordering, blocked selections and failure handling. They do not establish
successful live completion of all dungeons.

Blacksmiths map `87296515` is the final combat room. Victory transfers the player
to the separate exit room `87297539`, where Duncan (NPC `2030`) is present.
Session `20261112T182526_959396-0500` recorded this transfer twice, at `18:26:38`
and `18:32:49`. The old profile misidentified the combat room as the exit and
rejected Duncan's actual room as unexpected. The profile now attacks in the
combat room, talks to Duncan in `87297539`, then waits for dialog completion and
the outside map `88086786` before completing the cycle. Resuming in Duncan's
room requires no new key. Tests cover the entire flow and both exit event orders;
successful live completion of the corrected exit remains to be confirmed.

## Data and route references

The IDs, recommended levels, key definitions, NPC reply texts and passages are
checked against the repository's `DataReader`, `I18N` and `WorldGraphReader` data.
The exceptional room layouts were cross-checked with the
[Blacksmiths](https://www.dofuspourlesnoobs.com/donjon-des-forgerons.html),
[Scarafeuilles](https://www.dofuserie.com/donjons/donjon-des-scarafeuilles/) and
[Skeletons](https://www.dofuspourlesnoobs.com/donjon-des-squelettes.html) guides.
The [Valonia access guide](https://www.dofuspourlesnoobs.com/quetes-de-l-archipel-de-valonia.html)
describes the Madrestam boat and fare. The Skeletons guide confirms a pressure
plate followed by stairs, with an approximately ten-second window reported by
the user. The local graph has no incoming edge to crypt map `87032320`.
The user's plate `99` and session `20261112T191752_124575-0500` establish that
stepping there opens tomb cells `259`, `245`, `232`, `273`, `260`, `246`.
Obstacle updates are merged as deltas; server-opened cells override the static
out-of-combat walkability until closed again. The entrance action walks to the
tomb at `259` and requires the expected crypt map to load. This crossing still
needs live confirmation. All nine pending
profiles still require complete in-game validation, including the new boarding
dialogs and safe trap crossings. Kardorim is unchanged.


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


## Scarafeuilles trap antechamber

On map `94111744`, follow the user-supplied waypoints `486 -> 374 -> 287 -> 283`,
then approach the exit interactive on cell `267` from cell `282`. Each segment
waits for confirmed arrival before starting the next. The planner rejects detours
away from the straight segment instead of routing around it across unverified
floor cells. A pause during a segment retains its next waypoint while the bot
application remains open.

The world graph only identifies a fall at cell `384`. The recorded fall
trajectories ending at `441` and `429` are also excluded from planning. These
restrictions are local to the passage and do not modify the shared game map.
The final door interaction begins from its approach cell and does not replan a
second walk across the room. Automated tests verify the ordered movement and
door interaction; a successful live crossing is still pending confirmation.
