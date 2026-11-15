"""Independent numerical oracles for every equation in the library.

Each expected value below is worked out in SI units from first principles, written out
step by step in the test rather than by calling the library, so a unit slip, a wrong
constant or a swapped argument in `aerolab.core.equations` fails here. Where a value can
be checked by hand the hand result is quoted in a comment.

These are *consistency* checks (the code implements the stated formula with the stated
units). Recovery of numbers printed in the source papers lives in `validation.py` and
`test_core.py`; that split is described in docs/EQUATION_REGRESSION_REPORT.md.
"""
from __future__ import annotations

import math

import pytest

from aerolab.core import equations as E

# CODATA 2018 exact / recommended values, typed in independently of equations.py
KB = 1.380649e-23            # J/K (exact since 2019)
SIGMA = 5.670374419e-8       # W m^-2 K^-4
G_CM3 = 1000.0               # g/cm^3 -> kg/m^3
UM = 1e-6                    # µm -> m
NM = 1e-9
MW = 1e-3                    # mW/(m K) -> W/(m K)


def _k_gas(k0_mw, porosity_pct, d_nm, beta, mfp_nm):
    return k0_mw * porosity_pct / 100.0 / (1.0 + 2.0 * beta * mfp_nm / d_nm)


def _k_rad_mw(n, t_c, e_star_m2_g, rho_g_cm3):
    T = t_c + 273.15
    e_si = e_star_m2_g * 1000.0                # m^2/g -> m^2/kg
    rho_si = rho_g_cm3 * G_CM3
    return 16.0 * n ** 2 * SIGMA * T ** 3 / (3.0 * e_si * rho_si) / MW


# id -> (inputs, expected value in the equation's declared output unit)
ORACLES: dict[str, tuple[dict, float]] = {
    # ------------------------------------------------------------ structure
    # the papers' own algebraic form (1/rb - 1/rs)/(1/rb), not the code's 1 - rb/rs
    "porosity_from_density": ({"rho_b": 0.211, "rho_s": 1.058},
                              (1 / 0.211 - 1 / 1.058) / (1 / 0.211) * 100.0),
    "pore_volume": ({"rho_b": 0.211, "rho_s": 1.058}, 1 / 0.211 - 1 / 1.058),
    # 4 V / S with V in m^3/g and S in m^2/g gives metres: 4*3.79e-6/350.15 = 4.3296e-8 m
    "pore_diameter": ({"V_p": 3.79, "S": 350.15}, 4 * 3.79e-6 / 350.15 / NM),
    "skeletal_density_mixture": ({"w": (93.0, 7.0), "rho": (1.11, 1.006)},
                                 1.0 / (0.93 / 1.11 + 0.07 / 1.006)),
    "relative_density": ({"rho_b": 0.15, "rho_s": 1.116}, 0.15 / 1.116),
    "shrinkage": ({"V_final": 0.85, "V_initial": 1.0}, 15.0),
    "volume_fraction": ({"w_i": 0.02, "rho_i": 1.5, "w_m": 0.98, "rho_m": 1.11},
                        (0.02 / 1.5) / (0.02 / 1.5 + 0.98 / 1.11)),
    # mass per metre = area x density, in kg/m; tex = g per 1000 m. Hand: 0.9606 tex
    "fibre_areal_density": ({"D": 90.0, "rho": 0.151},
                            math.pi * (45 * UM) ** 2 * (0.151 * G_CM3) * 1000.0 * 1000.0),

    # ------------------------------------------------------------ thermal
    "k_total": ({"k_solid": 5.3, "k_gas": 18.7, "k_rad": 3.4, "k_conv": 0.5}, 27.9),
    "knudsen_number": ({"l_mfp": 70.0, "D": 30.0}, 70.0 / 30.0),
    "gas_conductivity_knudsen": ({"k_gas0": 26.0, "porosity": 86.5, "D": 30.0, "beta": 1.6,
                                  "l_mfp": 70.0}, _k_gas(26.0, 86.5, 30.0, 1.6, 70.0)),
    # Hand: kT = 4.1164e-21 J; sqrt(2) pi d^2 p = 5.965e-14 N/m -> 69.0 nm
    "mean_free_path": ({"T": 25.0, "d": 0.364, "p": 101325.0},
                       KB * 298.15 / (math.sqrt(2) * math.pi * (0.364 * NM) ** 2 * 101325.0) / NM),
    # Hand: 16 sigma T^3 = 24.05 W/m^2/K; 3 e* rho = 22650 m^-1 -> 1.062 mW/(m K)
    "radiative_conductivity": ({"n": 1.0, "T": 25.0, "e_star": 0.05, "rho": 0.151},
                               _k_rad_mw(1.0, 25.0, 0.05, 0.151)),
    "radiation_temperature_ratio": ({"T1": 25.0, "T2": 300.0}, (573.15 / 298.15) ** 3),
    # alpha = k/(rho cp) = 0.0277/(150.8*1000) m^2/s = 0.18369 mm^2/s
    "thermal_diffusivity": ({"k": 27.7, "rho": 0.1508, "c_p": 1000.0},
                            0.0277 / (150.8 * 1000.0) * 1e6),
    "thermal_effusivity": ({"k": 27.7, "rho": 0.1508, "c_p": 1000.0},
                           math.sqrt(0.0277 * 150.8 * 1000.0)),
    "effusivity_from_k_alpha": ({"k": 27.7, "alpha": 0.196}, 0.0277 / math.sqrt(0.196e-6)),
    "r_value": ({"t": 5.0, "k": 29.0}, 0.005 / 0.029),
    "clo_value": ({"R": 0.172}, 0.172 / 0.155),
    "k_model_aerogel_fibre": (
        {"k_s0": 1000.0, "rho_b": 0.1508, "rho_s": 1.116, "tau": 1.5, "D": 30.0, "beta": 1.6,
         "T": 25.0, "e_star": 0.05},
        1000.0 * (0.1508 / 1.116) ** 1.5
        + _k_gas(26.0, (1 - 0.1508 / 1.116) * 100.0, 30.0, 1.6, 70.0)
        + _k_rad_mw(1.0, 25.0, 0.05, 0.1508)),

    # ------------------------------------------------------------ mechanical
    # Hand: A = pi (45 µm)^2 = 6.3617e-9 m^2; 0.074 N / A = 11.632 MPa
    "tensile_stress": ({"F": 0.074, "D": 90.0}, 0.074 / (math.pi * (45 * UM) ** 2) / 1e6),
    "engineering_strain": ({"dL": 12.0, "L0": 80.0}, 15.0),
    "youngs_modulus": ({"sigma1": 0.2, "eps1": 1.0, "sigma2": 1.2, "eps2": 5.0}, 1.0 / 0.04),
    "specific_strength": ({"sigma": 11.6, "rho": 0.1508}, 11.6 / 0.1508),
    "second_moment_circle": ({"D": 90.0}, math.pi * (90 * UM) ** 4 / 64.0),
    "bending_rigidity": ({"E": 3.51, "D": 90.0}, 3.51e6 * math.pi * (90 * UM) ** 4 / 64.0),
    "euler_buckling": ({"E": 3.51, "D": 90.0, "L": 10.0, "K": 0.5},
                       math.pi ** 2 * 3.51e6 * (math.pi * (90 * UM) ** 4 / 64.0)
                       / (0.5 * 0.010) ** 2 * 1000.0),
    # Halpin-Kardos: xi = 2 l/d = 100, eta = (E_f/E_m - 1)/(E_f/E_m + xi) = 0.988024,
    # E = 12 (1 + 100*0.014623)/(1 - 0.014623) = 29.986 MPa
    "halpin_tsai": ({"E_m": 12.0, "E_f": 1e5, "phi_f": 0.0148, "l_over_d": 50.0},
                    12.0 * (1 + 100 * 0.0148 * (1e5 / 12 - 1) / (1e5 / 12 + 100))
                    / (1 - 0.0148 * (1e5 / 12 - 1) / (1e5 / 12 + 100))),
    "density_scaling_modulus": ({"E_m": 14.12, "rho": 0.1508, "rho_s": 1.116, "n": 0.78},
                                14.12 * math.exp(0.78 * math.log(0.1508 / 1.116))),
    "density_scaling_crosslinked": (
        {"E_m": 14.12, "rho": 0.1508, "rho_s": 1.116, "n": 0.78, "K": 33.65, "C": 0.04, "m": 1.39},
        14.12 * (0.1508 / 1.116) ** 0.78 + 33.65 * math.exp(1.39 * math.log(0.04))),
    "scaling_exponent_two_points": ({"rho1": 0.132, "E1": 9.15, "rho2": 0.157, "E2": 2.87},
                                    math.log(2.87 / 9.15) / math.log(0.157 / 0.132)),
    "elastic_recovery": ({"eps_max": 100.0, "PS": 5.3}, 94.7),
    "shape_recovery": ({"d2": 4.9, "d1": 5.0}, 98.0),

    # ------------------------------------------------------------ fatigue
    "swt_amplitude": ({"sigma_a": 3.6, "sigma_max": 7.2}, math.sqrt(25.92)),
    "strain_life": ({"sigma_f": 7.21, "E": 18.0, "b": -0.063, "eps_f": 0.34, "c": -0.14, "Nf": 1000.0},
                    7.21 / 18.0 * 2000.0 ** -0.063 + 0.34 * 2000.0 ** -0.14),
    "strain_life_morrow": ({"sigma_f": 7.21, "sigma_m": 1.0, "E": 18.0, "b": -0.063, "eps_f": 0.34,
                            "c": -0.14, "Nf": 1000.0},
                           6.21 / 18.0 * 2000.0 ** -0.063 + 0.34 * 2000.0 ** -0.14),
    "transition_life": ({"eps_f": 0.34, "E": 18.0, "sigma_f": 7.21, "b": -0.063, "c": -0.14},
                        (0.34 * 18.0 / 7.21) ** (1.0 / 0.077)),
    "ratcheting_strain": ({"eps_max": 64.0, "eps_min": 4.0}, 34.0),
    # inverse of sigma_a = sigma_f (2N)^b: put N = 5000 in, take sigma_a out, expect 5000 back
    "basquin_life": ({"sigma_a": 7.21 * 10000.0 ** -0.063, "sigma_f": 7.21, "b": -0.063}, 5000.0),

    # ------------------------------------------------------------ rheology
    "herschel_bulkley": ({"tau_y": 6000.0, "K": 50.0, "gamma_dot": 4.0, "n": 0.5}, 6100.0),
    "viscosity_ratio": ({"eta_d": 300.0, "eta_m": 600.0}, 0.5),
    # Ca = 600 Pa s * 100 1/s * 1e-6 m / 5e-3 N/m = 12
    "capillary_number": ({"eta_m": 600.0, "gamma_dot": 100.0, "R": 1.0, "Gamma": 5.0}, 12.0),
    # Q = 2 mL/h = 5.556e-10 m^3/s; A = 1.9856e-8 m^2 -> 1.6788 m/min; DR = 1/1.6788
    "draw_ratio": ({"V_takeup": 1.0, "Q": 2.0, "d_nozzle": 159.0},
                   1.0 / ((2e-6 / 3600.0) / (math.pi * (79.5 * UM) ** 2) * 60.0)),
    "nozzle_exit_velocity": ({"Q": 2.0, "d_nozzle": 159.0},
                             (2e-6 / 3600.0) / (math.pi * (79.5 * UM) ** 2) * 60.0),
    "tan_delta": ({"G_storage": 30000.0, "G_loss": 5000.0}, math.degrees(math.atan(1 / 6))),
    "complex_modulus": ({"G_storage": 30000.0, "G_loss": 5000.0}, math.sqrt(30000.0 ** 2 + 5000.0 ** 2)),
    "diffusion_time": ({"R": 50.0, "D_diff": 1e-9}, 2.5),
    "deborah_recovery": ({"t_rec": 1.0, "t_tr": 2.0}, 0.5),
    "yield_number": ({"tau_y": 6000.0, "R": 250.0, "Gamma": 5.0}, 300.0),

    # ------------------------------------------------------------ chemistry
    "gel_content": ({"W_gel": 82.0, "W_0": 100.0}, 82.0),
    "crystallinity_xrd": ({"A_cryst": 78.0, "A_total": 100.0}, 78.0),
    "crystallinity_dsc": ({"dH_m": 9.49, "dH_cc": 2.0, "w": 0.67, "dH_100": 196.8},
                          7.49 / (0.67 * 196.8) * 100.0),
    "normalised_enthalpy": ({"dH": 7.49, "w_polymer": 0.67}, 7.49 / 0.67),
    "wetting_coefficient": ({"g13": 5.0, "g23": 12.0, "g12": 4.0}, -1.75),

    # ------------------------------------------------------------ scattering
    "saxs_q_to_d": ({"q": 0.53}, 2 * math.pi / 0.53),
    # lambda = 1.54 Å = 0.154 nm: q = 4 pi sin(0.5°)/0.154 = 0.71207 1/nm
    "scattering_vector": ({"lambda_": 1.54, "theta": 0.5},
                          4 * math.pi * math.sin(math.radians(0.5)) / 0.154),
    # Cu Kα at 2θ = 22°: d = 0.15406/(2 sin 11°) = 0.40370 nm (≈4.04 Å)
    "bragg_spacing": ({"lambda_": 1.5406, "two_theta": 22.0},
                      0.15406 / (2 * math.sin(math.radians(11.0)))),
    # Scherrer: 0.9*0.15406 nm/(0.0087266 rad * cos 11°) = 16.19 nm
    "scherrer_size": ({"K": 0.9, "lambda_": 1.5406, "beta": 0.5, "two_theta": 22.0},
                      0.9 * 0.15406 / (math.radians(0.5) * math.cos(math.radians(11.0)))),
    "long_period": ({"q_max": 0.69}, 2 * math.pi / 0.69),
}


def test_every_equation_has_an_independent_oracle():
    assert set(ORACLES) == set(E.REGISTRY), (
        "missing: " + ", ".join(sorted(set(E.REGISTRY) - set(ORACLES)))
        + " | stale: " + ", ".join(sorted(set(ORACLES) - set(E.REGISTRY))))


@pytest.mark.parametrize("eq_id", sorted(ORACLES))
def test_equation_matches_first_principles(eq_id):
    inputs, expected = ORACLES[eq_id]
    value = float(E.get(eq_id).compute(**inputs))
    assert value == pytest.approx(expected, rel=1e-6), f"{eq_id}: {value} != {expected}"


# Hand values quoted above, so a slip in the oracle arithmetic itself would also show.
@pytest.mark.parametrize("eq_id,hand,rel", [
    ("pore_diameter", 43.296, 1e-4),
    ("fibre_areal_density", 0.9606, 1e-3),
    ("mean_free_path", 69.0, 2e-3),
    ("radiative_conductivity", 1.0616, 1e-3),
    ("radiation_temperature_ratio", 7.104, 1e-3),
    ("thermal_diffusivity", 0.18369, 1e-4),
    ("thermal_effusivity", 64.631, 1e-4),
    ("effusivity_from_k_alpha", 62.568, 1e-4),
    ("tensile_stress", 11.632, 1e-4),
    ("halpin_tsai", 29.986, 1e-4),
    ("nozzle_exit_velocity", 1.6788, 1e-4),
    ("draw_ratio", 0.59567, 1e-4),
    ("tan_delta", 9.4623, 1e-4),
    ("scattering_vector", 0.71207, 1e-4),
    ("bragg_spacing", 0.40370, 1e-4),
    ("scherrer_size", 16.186, 1e-3),
])
def test_hand_worked_values(eq_id, hand, rel):
    inputs, _expected = ORACLES[eq_id]
    assert float(E.get(eq_id).compute(**inputs)) == pytest.approx(hand, rel=rel)


# --------------------------------------------------------------- limits and identities
def test_porosity_limits():
    eq = E.get("porosity_from_density")
    assert float(eq.compute(rho_b=1.0, rho_s=1.0)) == pytest.approx(0.0, abs=1e-12)
    assert float(eq.compute(rho_b=0.0, rho_s=1.0)) == pytest.approx(100.0)


def test_porosity_and_pore_volume_are_consistent():
    """ε = V_p ρ_b (pore volume per envelope volume) for any pair of densities."""
    for rb, rs in ((0.211, 1.058), (0.05, 2.2), (0.9, 1.0)):
        eps = float(E.get("porosity_from_density").compute(rho_b=rb, rho_s=rs))
        vp = float(E.get("pore_volume").compute(rho_b=rb, rho_s=rs))
        assert eps / 100.0 == pytest.approx(vp * rb, rel=1e-12)


def test_halpin_tsai_limits():
    eq = E.get("halpin_tsai")
    assert float(eq.compute(E_m=12.0, E_f=1e5, phi_f=0.0, l_over_d=50.0)) == pytest.approx(12.0)
    assert float(eq.compute(E_m=12.0, E_f=12.0, phi_f=0.3, l_over_d=50.0)) == pytest.approx(12.0)
    # infinite aspect ratio -> rule of mixtures (Voigt bound)
    voigt = 0.3 * 1000.0 + 0.7 * 12.0
    assert float(eq.compute(E_m=12.0, E_f=1000.0, phi_f=0.3, l_over_d=1e9)) == pytest.approx(voigt, rel=1e-6)


def test_effusivity_forms_agree():
    """e = sqrt(k rho cp) and e = k/sqrt(alpha) are the same quantity when alpha = k/(rho cp)."""
    k, rho, cp = 27.7, 0.1508, 1000.0
    alpha = float(E.get("thermal_diffusivity").compute(k=k, rho=rho, c_p=cp))
    e1 = float(E.get("thermal_effusivity").compute(k=k, rho=rho, c_p=cp))
    e2 = float(E.get("effusivity_from_k_alpha").compute(k=k, alpha=alpha))
    assert e1 == pytest.approx(e2, rel=1e-12)


def test_draw_ratio_is_takeup_over_exit_velocity():
    v_exit = float(E.get("nozzle_exit_velocity").compute(Q=2.0, d_nozzle=159.0))
    dr = float(E.get("draw_ratio").compute(V_takeup=3.0, Q=2.0, d_nozzle=159.0))
    assert dr == pytest.approx(3.0 / v_exit, rel=1e-12)


def test_transition_life_is_where_the_two_branches_are_equal():
    p = {"eps_f": 0.34, "E": 18.0, "sigma_f": 7.21, "b": -0.063, "c": -0.14}
    two_nt = float(E.get("transition_life").compute(**p))
    elastic = p["sigma_f"] / p["E"] * two_nt ** p["b"]
    plastic = p["eps_f"] * two_nt ** p["c"]
    assert elastic == pytest.approx(plastic, rel=1e-9)


def test_k_model_breakdown_sums_to_the_registered_equation():
    args = dict(k_s0=1000.0, rho_b=0.1508, rho_s=1.116, tau=1.5, D=30.0, beta=1.6, T=25.0, e_star=0.05)
    parts = E.k_model_breakdown(**args)
    assert parts["k_total"] == pytest.approx(float(E.get("k_model_aerogel_fibre").compute(**args)), rel=1e-12)
    assert parts["k_solid"] + parts["k_gas"] + parts["k_rad"] == pytest.approx(parts["k_total"], rel=1e-12)


def test_rule_of_mixtures_rejects_mismatched_lists():
    with pytest.raises(ValueError):
        E.get("skeletal_density_mixture").compute(w=(0.5, 0.5), rho=(1.0,))
