"""League, scoring and rule configuration.

Every knob the spec calls out as "configurable" lives here rather than being
hardcoded into the scoring or rule code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Positions that fill exactly one starting slot per team, so their replacement
# rank is simply the number of teams in the league.
SINGLE_SLOT_POSITIONS = ("QB", "TE", "K", "DST")

# Positions that share the FLEX pool and therefore share a replacement baseline.
FLEX_POSITIONS = ("RB", "WR")

ALL_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


@dataclass
class LeagueSettings:
    """League shape. Drives replacement level, roster caps and snake ordering."""

    n_teams: int = 12
    my_slot: int = 1  # 1-indexed draft slot

    # Starting roster construction (spec section 1 defaults).
    qb: int = 1
    rb: int = 2
    wr: int = 2
    te: int = 1
    flex: int = 1
    k: int = 1
    dst: int = 1
    bench: int = 6

    stats_year: int = 2025  # season the VOR numbers come from
    adp_year: int = 2026  # season being drafted

    @property
    def starters(self) -> int:
        return self.qb + self.rb + self.wr + self.te + self.flex + self.k + self.dst

    @property
    def roster_size(self) -> int:
        return self.starters + self.bench

    @property
    def total_rounds(self) -> int:
        return self.roster_size

    @property
    def total_picks(self) -> int:
        return self.n_teams * self.total_rounds

    @property
    def flex_pool_size(self) -> int:
        """Shared RB/WR replacement rank: N x (RB + WR + FLEX) slots."""
        return self.n_teams * (self.rb + self.wr + self.flex)

    def starting_slots(self, position: str) -> int:
        """Starting slots for a position, ignoring FLEX."""
        return {
            "QB": self.qb,
            "RB": self.rb,
            "WR": self.wr,
            "TE": self.te,
            "K": self.k,
            "DST": self.dst,
        }[position]


@dataclass
class EnsembleWeights:
    """Weights for the four scores in spec section 3.

    Scores 2 and 3 are computed and stored but weighted zero for v1 -- the spec
    wants that data tracked before it counts toward a pick. The spec's nominal
    0.6 / 0.15 / 0.15 / 0.1 renormalizes to 0.857 / 0 / 0 / 0.143 once the middle
    two are zeroed, which preserves the intended 6:1 ratio between VOR and the
    ADP value gap.
    """

    vor: float = 0.857
    games_adjusted: float = 0.0
    consistency: float = 0.0
    adp_gap: float = 0.143

    def normalized(self) -> "EnsembleWeights":
        total = self.vor + self.games_adjusted + self.consistency + self.adp_gap
        if total <= 0:
            raise ValueError("ensemble weights must sum to something positive")
        return EnsembleWeights(
            vor=self.vor / total,
            games_adjusted=self.games_adjusted / total,
            consistency=self.consistency / total,
            adp_gap=self.adp_gap / total,
        )


@dataclass
class RuleConfig:
    """Thresholds for the draft recommendation rules (spec section 4)."""

    # Rule 3 -- this bot only supports 1QB / 1TE leagues, but the caps are
    # expressed as config so superflex is a config change rather than a rewrite.
    max_qb: int = 1
    max_te: int = 1

    # Rule 2 -- balance guard trips at a difference of this many or more.
    rb_wr_imbalance: int = 3

    # Rule 5 -- anti-reach. Skip players whose ADP is more than this many picks
    # later than the current pick number.
    reach_threshold: int = 20

    # Rule 6 -- below this VOR, fall back to drafting by ADP.
    low_vor_floor: float = 0.5

    # Spec section 2 -- small-sample filter.
    min_games: int = 9

    # Review section -- positional VOR drop-off before the next projected pick.
    dropoff_threshold: float = 0.40
    dropoff_max_bonus: float = 12.0

    # Run-heavy team RB boost.
    rush_rank_top_n: int = 10
    rush_rank_basis: str = "rb_carries"  # or "team_carries"
    rush_boost: float = 6.0

    # Bye-week starter collision penalty.
    bye_penalty: float = 4.0

    def __post_init__(self) -> None:
        if self.rush_rank_basis not in ("rb_carries", "team_carries"):
            raise ValueError(
                f"rush_rank_basis must be 'rb_carries' or 'team_carries', "
                f"got {self.rush_rank_basis!r}"
            )


@dataclass
class Config:
    league: LeagueSettings = field(default_factory=LeagueSettings)
    weights: EnsembleWeights = field(default_factory=EnsembleWeights)
    rules: RuleConfig = field(default_factory=RuleConfig)
