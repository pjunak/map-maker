"""Pinned Landlab boundary for the reference experiment, imported only on demand."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from time import perf_counter
from typing import Any

import numpy as np
from numpy.typing import NDArray

from benchmarks.evolution.scenarios import EvolutionFields, FloatArray, frozen
from map_maker.terrain.domain.evolution import EvolutionBudget, EvolutionEpoch, EvolutionHistory


class EvolutionBudgetExceeded(RuntimeError):
    """No final state may be published as a completed history after this error."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    name: str
    time_years: float
    elevation_m: FloatArray
    receiver: NDArray[np.int64]
    area_m2: FloatArray
    discharge_m3_per_year: FloatArray
    depression_depth_m: FloatArray


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    snapshots: tuple[Snapshot, ...]
    uplift_m: FloatArray
    incision_m: FloatArray
    diffusion_change_m: FloatArray
    steps: tuple[dict[str, float | str], ...]
    trials: int
    rejected_trials: int
    diffusion_boundary_export_m3: float
    balance_residual_m3: float
    seconds: float
    stage_seconds: dict[str, float]


@dataclass(frozen=True, slots=True)
class StepChange:
    uplift_m: FloatArray
    incision_m: FloatArray
    diffusion_change_m: FloatArray
    boundary_export_m3: float


class LandlabReference:
    """Own a mutable engine grid; external arrays are copied and never mutated.

    The external package is intentionally untyped at this narrow research boundary.
    All arrays returned to our code have explicit NumPy types and owned snapshots.
    """

    def __init__(self, fields: EvolutionFields, history: EvolutionHistory) -> None:
        try:
            package = import_module("landlab")
            components = import_module("landlab.components")
        except ImportError as error:
            raise RuntimeError(
                "Use the isolated evolution environment; see benchmarks/evolution/README.md."
            ) from error
        self.fields = fields
        self.history = history
        self.grid: Any = package.RasterModelGrid(fields.grid.shape,
                                                 xy_spacing=fields.grid.spacing_m)
        self.grid.add_field("topographic__elevation", fields.initial_m.ravel().copy(), at="node")
        self.z: FloatArray = np.asarray(
            self.grid.at_node["topographic__elevation"], dtype=np.float64)
        self.core: NDArray[np.bool_] = fields.core.ravel()
        self.boundary = ~self.core
        self.fixed: FloatArray = self.z[self.boundary].copy()
        self.area: FloatArray = np.asarray(self.grid.cell_area_at_node, dtype=np.float64)
        self.grid.add_field("water__unit_flux_in", np.zeros(self.z.shape), at="node")
        self.router: Any = components.FlowAccumulator(
            self.grid, flow_director="D8",
            depression_finder="DepressionFinderAndRouter",
        )
        self.eroder: Any = components.FastscapeEroder(
            self.grid, K_sp=0., m_sp=history.discharge_exponent, n_sp=1.,
            discharge_field="surface_water__discharge", erode_flooded_nodes=False,
        )
        self._accumulate: Any = import_module(
            "landlab.components.flow_accum").find_drainage_area_and_discharge
        self._diffuser_type: Any = components.LinearDiffuser
        self.diffuser: Any = None
        self.stage_seconds = {"routing": 0., "incision": 0., "diffusion": 0.}
        tail = np.asarray(self.grid.node_at_link_tail, dtype=np.int64)
        head = np.asarray(self.grid.node_at_link_head, dtype=np.int64)
        self._boundary_sign = self.core[tail].astype(np.int8) - self.core[head].astype(np.int8)
        self._boundary_sign[np.asarray(self.grid.status_at_link) != 0] = 0

    def set_epoch(self, epoch: EvolutionEpoch) -> None:
        runoff = np.asarray(self.grid.at_node["water__unit_flux_in"])
        runoff[:] = epoch.runoff_m_per_year * self.fields.runoff_weight.ravel()
        runoff[self.boundary] = 0.
        normalization = (self.history.reference_discharge_m3_per_year
                         ** self.history.discharge_exponent)
        self._erodibility = (epoch.erodibility_m_per_year
                             / self.fields.resistance.ravel() / normalization)
        self.diffuser = (self._diffuser_type(self.grid,
                                           linear_diffusivity=epoch.diffusivity_m2_per_year,
                                           method="simple", deposit=True)
                         if epoch.diffusivity_m2_per_year else None)

    def route(self) -> None:
        started = perf_counter()
        self.router.run_one_step()
        # Landlab 2.11's discharge path narrows each sum through a C float.
        # Its public area accumulator uses Float64 additions. Accumulate the
        # local volumetric source as weights through that branch, then restore
        # physical discharge. This also handles spatially varying runoff.
        local = self.area * np.asarray(self.grid.at_node["water__unit_flux_in"], dtype=np.float64)
        discharge, _ = self._accumulate(
            self.grid.at_node["flow__upstream_node_order"],
            self.grid.at_node["flow__receiver_node"], node_cell_area=local, runoff=0.,
        )
        self.grid.at_node["surface_water__discharge"][:] = discharge
        self.stage_seconds["routing"] += perf_counter() - started
        discharge = np.asarray(self.grid.at_node["surface_water__discharge"], dtype=np.float64)
        if not np.all(np.isfinite(discharge)) or np.any(discharge < 0):
            raise RuntimeError("Routing produced invalid discharge.")
        # Explicitly disable dry-node incision, including the m=0 control case.
        self.eroder.K = np.where(discharge > 0, self._erodibility, 0.)

    def step(
        self, epoch: EvolutionEpoch, years: float, check_budget: Callable[[], None],
    ) -> StepChange:
        check_budget()
        uplift = years * epoch.uplift_m_per_year * self.fields.uplift_weight.ravel()
        uplift[self.boundary] = 0.
        self.z[:] += uplift
        self.route()
        before = self.z.copy()
        started = perf_counter()
        if epoch.erodibility_m_per_year:
            self.eroder.run_one_step(years)
        self.stage_seconds["incision"] += perf_counter() - started
        incision = before - self.z
        if np.any(incision < -1.e-8):
            raise RuntimeError("Incision raised ground along an adverse receiver.")
        before[:] = self.z
        export = 0.
        started = perf_counter()
        if self.diffuser is not None:
            # Keep each call below the scalar-diffusivity CFL limit. Its recorded
            # link flux then covers this whole substep, not merely its final subcycle.
            stable_step = .1 * self.fields.grid.spacing_m**2 / epoch.diffusivity_m2_per_year
            remaining = years
            while remaining > 0:
                check_budget()
                dt = min(remaining, stable_step)
                if remaining - dt == remaining:
                    raise EvolutionBudgetExceeded("Diffusion cannot advance at this time scale.")
                self.diffuser.run_one_step(dt)
                flux = np.asarray(self.grid.at_link["hillslope_sediment__unit_volume_flux"])
                export += float(np.dot(flux, self._boundary_sign)) * self.fields.grid.spacing_m * dt
                remaining = 0. if dt == remaining else remaining - dt
        self.stage_seconds["diffusion"] += perf_counter() - started
        if (not np.all(np.isfinite(self.z)) or np.any(self.z < -1.e-8)
                or not np.array_equal(self.z[self.boundary], self.fixed)):
            raise RuntimeError("Evolution violated finite, nonnegative or fixed-boundary ground.")
        check_budget()
        return StepChange(uplift, incision, self.z - before, export)

    def snapshot(self, name: str, time_years: float) -> Snapshot:
        shape = self.fields.grid.shape
        receiver = np.asarray(self.grid.at_node["flow__receiver_node"], dtype=np.int64).copy()
        receiver[receiver == np.arange(receiver.size)] = -1
        receiver = receiver.reshape(shape)
        receiver.flags.writeable = False
        return Snapshot(
            name, time_years, frozen(self.z.reshape(shape)), receiver,
            frozen(np.asarray(self.grid.at_node["drainage_area"]).reshape(shape)),
            frozen(np.asarray(self.grid.at_node["surface_water__discharge"]).reshape(shape)),
            frozen(np.asarray(self.grid.at_node["depression__depth"]).reshape(shape)),
        )


def evolve(
    fields: EvolutionFields, history: EvolutionHistory, budget: EvolutionBudget,
    *, progress: Callable[[dict[str, float | str]], None] | None = None,
) -> EvolutionResult:
    """Accept two half-steps after a full-step error check; rollback failed trials."""
    started = perf_counter()

    def check_budget() -> None:
        if perf_counter() - started > budget.maximum_seconds:
            raise EvolutionBudgetExceeded("Evolution exceeded its wall-time budget.")

    engine = LandlabReference(fields, history)
    engine.set_epoch(history.epochs[0])
    engine.route()
    snapshots = [engine.snapshot("initial", 0.)]
    total_uplift = np.zeros(engine.z.shape)
    total_incision = np.zeros(engine.z.shape)
    total_diffusion = np.zeros(engine.z.shape)
    steps: list[dict[str, float | str]] = []
    total_export = 0.
    time_years = 0.
    trials = rejected = 0
    for epoch in history.epochs:
        engine.set_epoch(epoch)
        epoch_start = time_years
        elapsed = 0.
        candidate_dt = budget.maximum_step_years
        while elapsed < epoch.duration_years:
            check_budget()
            if len(steps) >= budget.maximum_steps or trials >= budget.maximum_trials:
                raise EvolutionBudgetExceeded("Evolution exhausted its step/trial budget.")
            dt = min(candidate_dt, epoch.duration_years - elapsed)
            if elapsed + dt == elapsed:
                raise EvolutionBudgetExceeded("Evolution time step cannot advance the epoch.")
            trials += 1
            original = engine.z.copy()
            previous_receivers = np.asarray(
                engine.grid.at_node["flow__receiver_node"], dtype=np.int64).copy()
            engine.step(epoch, dt, check_budget)
            coarse = engine.z.copy()
            engine.z[:] = original
            first = engine.step(epoch, .5*dt, check_budget)
            second = engine.step(epoch, .5*dt, check_budget)
            error = float(np.max(np.abs(engine.z - coarse)))
            if error > budget.step_error_m:
                engine.z[:] = original
                engine.route()
                check_budget()
                rejected += 1
                candidate_dt = .5*dt
                if candidate_dt < budget.minimum_step_years:
                    raise EvolutionBudgetExceeded(
                        "Accuracy tolerance requires a smaller permitted step.")
                continue
            engine.route()
            check_budget()
            current_receivers = np.asarray(
                engine.grid.at_node["flow__receiver_node"], dtype=np.int64)
            changed: NDArray[np.bool_] = current_receivers != previous_receivers
            total_uplift += first.uplift_m + second.uplift_m
            total_incision += first.incision_m + second.incision_m
            total_diffusion += first.diffusion_change_m + second.diffusion_change_m
            total_export += first.boundary_export_m3 + second.boundary_export_m3
            elapsed = (epoch.duration_years if dt == epoch.duration_years - elapsed
                       else elapsed + dt)
            time_years = epoch_start + elapsed
            row: dict[str, float | str] = {
                "epoch": epoch.name, "time_years": time_years, "step_years": dt,
                "step_error_m": error,
                "changed_receiver_area_fraction": float(np.mean(changed[engine.core])),
            }
            steps.append(row)
            if progress is not None and (len(steps) % 25 == 0 or elapsed == epoch.duration_years):
                progress(row)
            if error < budget.step_error_m / 8:
                candidate_dt = min(budget.maximum_step_years, 2.*dt)
        engine.route()
        snapshots.append(engine.snapshot(epoch.name, time_years))
    check_budget()
    delta = float(np.dot(engine.z - fields.initial_m.ravel(), engine.area))
    imposed = float(np.dot(total_uplift, engine.area))
    removed = float(np.dot(total_incision, engine.area))
    residual = delta - (imposed - removed - total_export)
    return EvolutionResult(
        tuple(snapshots), frozen(total_uplift.reshape(fields.grid.shape)),
        frozen(total_incision.reshape(fields.grid.shape)),
        frozen(total_diffusion.reshape(fields.grid.shape)), tuple(steps), trials, rejected,
        total_export, residual, perf_counter()-started, dict(engine.stage_seconds),
    )
