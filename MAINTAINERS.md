# Maintainers and governance

Robo Use is developed by [BenchFlow](https://benchflow.ai) and maintained by the people below.

| Maintainer | GitHub | Areas |
|---|---|---|
| Xiangyi Li | [@xdotli](https://github.com/xdotli) | everything: releases, the task format, scoring, the sandbox, docs |

## How decisions are made

- The maintainers review and merge pull requests. Every pull request needs one maintainer's approval.
- Changes to the task format, scoring, the episode server or the sandbox are discussed in an issue first, because they change what published scores mean. A maintainer decides when there is no agreement, and records the reason in the issue.
- Releases are cut by a maintainer, after the release gate (`tools/gate.py`): reference solutions must score 1 and no-op controls 0 on every CPU suite. Each release is listed in [CHANGELOG.md](CHANGELOG.md).
- Published results on [robouse.ai/runs](https://robouse.ai/runs/) come from runs the maintainers made and audited. When an audit finds a trial that should not count, the maintainers remove or re-run it and say so on the site.

## Becoming a maintainer

Contributors who have made sustained, high-quality contributions, such as several merged pull requests in one area and helpful reviews, may be invited by the current maintainers. Ask on the BenchFlow [Discord](https://discord.gg/mZ9Rc8q8W3) if you are interested.

## Contact

- Conduct: xiangyi@benchflow.ai ([Code of Conduct](CODE_OF_CONDUCT.md))
- Security: private reports as [SECURITY.md](SECURITY.md) describes
