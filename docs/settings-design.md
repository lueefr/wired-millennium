# Settings design

The design follows Steam's native controls, colors and type rather than introducing an independent visual system. It applies [Nielsen Norman Group's usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): visible save status, consistent controls, error prevention, and helpful failure messages. [Progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) keeps less-used operations out of the main provider screen.

## Interaction decisions

- Providers, Downloads, Cloud and Tools are separate tabs. Only the selected panel is rendered.
- API keys persist after a 450 ms input pause. Switches persist immediately. Writes are serialized and include the latest configuration, preventing rapid edits from reverting one another.
- Persistence status is visible and announced through a polite live region. Errors do not claim the setting was saved.
- A single account action is shown for each state: sign in, cancel pending sign-in, or sign out.
- Adding to the library never starts installation. Fixes require both an added and installed game.
- Cloud changes remain a draft until Save and restart because they can migrate data and restart Steam. Migration has explicit choices and keeps its source.
- Custom sources are edited as a coherent record and validated before saving. This is an appropriate explicit save operation because a partially typed URL is invalid.
- Advanced S3 options are collapsed. R2/S3 inputs use a responsive two-column grid when space allows.
- The cloud game inventory has its own view and five items per page. Unbounded lists do not make the connection screen grow.
- No fixed-height clipping is used. Common screens are kept compact, but small windows, accessibility zoom or long translations may still need scrolling.

These are engineering and heuristic decisions, not claims of user-tested usability. Automated checks verify behavior, localization and common viewport layouts; real Steam themes and native-speaker reviews remain useful.

Component update dialogs use native modal controls and plain-text changelogs. The user can defer a revision persistently, or explicitly approve preparation and installation after Steam closes. Source-only changes never masquerade as installable binaries. Scheduled checks use fixed local times with a single catch-up run.
