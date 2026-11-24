"""Warp kernels for the GPU DFSPH prototype. Each kernel mirrors one loop of SPlisHSPlasH 2.19.0 (float32 'Real'):
TimeStep::computeDensities, TimeStepDFSPH::{computeDFSPHFactor, computeDensityAdv, computeDensityChange,
computePressureAccel, pressureSolveIteration, divergenceSolveIteration}, Viscosity_Weiler2018::{matrixVecProd,
diagonalMatrixElement, computeRHS}, SurfaceTension_Jeske2023::{computeDensityGradient, matrixVecProd, computeRHS}
with Akinci2012 boundary particles, and the Eigen conjugate-gradient driver (see solver.py).

Neighbour lists are built once per substep (fixed capacity per particle) together with W and grad W of every pair,
like SPlisHSPlasH's precomputeValues; boundary volumes are Akinci's 1 / sum W over the body's own samples.
"""
from __future__ import annotations

import warp as wp

PI = 3.14159265358979323846


@wp.func
def cubic_w(r: wp.vec3, h: float) -> float:
    k = 8.0 / (PI * h * h * h)
    q = wp.length(r) / h
    res = float(0.0)
    if q <= 1.0:
        if q <= 0.5:
            q2 = q * q
            res = k * (6.0 * q2 * q - 6.0 * q2 + 1.0)
        else:
            f = 1.0 - q
            res = k * 2.0 * f * f * f
    return res


@wp.func
def cubic_gradw(r: wp.vec3, h: float) -> wp.vec3:
    l = 48.0 / (PI * h * h * h)
    rl = wp.length(r)
    q = rl / h
    res = wp.vec3(0.0, 0.0, 0.0)
    if rl > 1.0e-6 and q <= 1.0:
        gradq = r / (rl * h)
        if q <= 0.5:
            res = l * q * (3.0 * q - 2.0) * gradq
        else:
            f = 1.0 - q
            res = l * (-f * f) * gradq
    return res


@wp.func
def cubic_w0(h: float) -> float:
    return 8.0 / (PI * h * h * h)


# ---- boundaries -------------------------------------------------------------------------------------------------
@wp.kernel
def boundary_update(x0: wp.array(dtype=wp.vec3), body: wp.array(dtype=int), bpos: wp.array(dtype=wp.vec3),
                    brot: wp.array(dtype=wp.mat33), bvel: wp.array(dtype=wp.vec3), bang: wp.array(dtype=wp.vec3),
                    offset: int, x: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3)):
    i = wp.tid() + offset
    b = body[i]
    xi = brot[b] * x0[i] + bpos[b]
    x[i] = xi
    v[i] = wp.cross(bang[b], xi - bpos[b]) + bvel[b]


@wp.kernel
def boundary_volume(grid: wp.uint64, xb: wp.array(dtype=wp.vec3), h: float, vol: wp.array(dtype=float)):
    """Akinci psi: 1 / sum_k W(x_i - x_k) over the samples in `grid` (the body itself), self term W(0) included."""
    i = wp.tid()
    xi = xb[i]
    delta = float(cubic_w0(h))
    q = wp.hash_grid_query(grid, xi, h)
    j = int(0)
    while wp.hash_grid_query_next(q, j):
        if j != i:
            d = xi - xb[j]
            if wp.length(d) <= h:
                delta += cubic_w(d, h)
    vol[i] = 1.0 / delta


# ---- neighbours -------------------------------------------------------------------------------------------------
@wp.kernel
def build_neighbours(grid_f: wp.uint64, grid_s: wp.uint64, grid_d: wp.uint64, x: wp.array(dtype=wp.vec3),
                     xb: wp.array(dtype=wp.vec3), n_static: int, has_dynamic: int, h: float,
                     nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int), gw_f: wp.array2d(dtype=wp.vec3),
                     w_f: wp.array2d(dtype=float), nn_b: wp.array2d(dtype=int), cnt_b: wp.array(dtype=int),
                     gw_b: wp.array2d(dtype=wp.vec3), w_b: wp.array2d(dtype=float), overflow: wp.array(dtype=int)):
    i = wp.tid()
    xi = x[i]
    kf = nn_f.shape[1]
    kb = nn_b.shape[1]
    c = int(0)
    q = wp.hash_grid_query(grid_f, xi, h)
    j = int(0)
    while wp.hash_grid_query_next(q, j):
        if j != i:
            d = xi - x[j]
            if wp.length(d) <= h:
                if c < kf:
                    nn_f[i, c] = j
                    gw_f[i, c] = cubic_gradw(d, h)
                    w_f[i, c] = cubic_w(d, h)
                else:
                    overflow[0] = 1
                c += 1
    cnt_f[i] = wp.min(c, kf)
    c = int(0)
    q = wp.hash_grid_query(grid_s, xi, h)
    while wp.hash_grid_query_next(q, j):
        d = xi - xb[j]
        if wp.length(d) <= h:
            if c < kb:
                nn_b[i, c] = j
                gw_b[i, c] = cubic_gradw(d, h)
                w_b[i, c] = cubic_w(d, h)
            else:
                overflow[0] = 1
            c += 1
    if has_dynamic == 1:
        q = wp.hash_grid_query(grid_d, xi, h)
        while wp.hash_grid_query_next(q, j):
            jj = j + n_static
            d = xi - xb[jj]
            if wp.length(d) <= h:
                if c < kb:
                    nn_b[i, c] = jj
                    gw_b[i, c] = cubic_gradw(d, h)
                    w_b[i, c] = cubic_w(d, h)
                else:
                    overflow[0] = 1
                c += 1
    cnt_b[i] = wp.min(c, kb)


# ---- DFSPH ------------------------------------------------------------------------------------------------------
@wp.kernel
def density(cnt_f: wp.array(dtype=int), w_f: wp.array2d(dtype=float), nn_b: wp.array2d(dtype=int),
            cnt_b: wp.array(dtype=int), w_b: wp.array2d(dtype=float), vb: wp.array(dtype=float), vol: float,
            rho0: float, h: float, rho: wp.array(dtype=float)):
    i = wp.tid()
    d = vol * cubic_w0(h)
    for k in range(cnt_f[i]):
        d += vol * w_f[i, k]
    for k in range(cnt_b[i]):
        d += vb[nn_b[i, k]] * w_b[i, k]
    rho[i] = d * rho0


@wp.kernel
def dfsph_factor(cnt_f: wp.array(dtype=int), gw_f: wp.array2d(dtype=wp.vec3), nn_b: wp.array2d(dtype=int),
                 cnt_b: wp.array(dtype=int), gw_b: wp.array2d(dtype=wp.vec3), vb: wp.array(dtype=float), vol: float,
                 eps: float, factor: wp.array(dtype=float)):
    i = wp.tid()
    sum_grad = float(0.0)
    grad_i = wp.vec3(0.0, 0.0, 0.0)
    for k in range(cnt_f[i]):
        g = -vol * gw_f[i, k]
        sum_grad += wp.dot(g, g)
        grad_i -= g
    for k in range(cnt_b[i]):
        grad_i -= -vb[nn_b[i, k]] * gw_b[i, k]
    sum_grad += wp.dot(grad_i, grad_i)
    if sum_grad > eps:
        factor[i] = 1.0 / sum_grad
    else:
        factor[i] = 0.0


@wp.kernel
def density_adv(v: wp.array(dtype=wp.vec3), nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int),
                gw_f: wp.array2d(dtype=wp.vec3), nn_b: wp.array2d(dtype=int), cnt_b: wp.array(dtype=int),
                gw_b: wp.array2d(dtype=wp.vec3), vb: wp.array(dtype=float), velb: wp.array(dtype=wp.vec3), vol: float,
                rho: wp.array(dtype=float), rho0: float, dt: float, mode: int, factor: wp.array(dtype=float),
                p: wp.array(dtype=float), dadv: wp.array(dtype=float)):
    """mode 0: pressure solve (rho_adv = rho/rho0 + dt * delta, factor /= dt^2, warm start p);
    mode 1: divergence solve (rho_adv = max(delta, 0), zero with < 20 neighbours, factor /= dt, warm start p_v)."""
    i = wp.tid()
    vi = v[i]
    delta = float(0.0)
    for k in range(cnt_f[i]):
        delta += wp.dot(vi - v[nn_f[i, k]], vol * gw_f[i, k])
    for k in range(cnt_b[i]):
        j = nn_b[i, k]
        delta += vb[j] * wp.dot(vi - velb[j], gw_b[i, k])
    if mode == 0:
        da = rho[i] / rho0 + dt * delta
        dadv[i] = da
        factor[i] = factor[i] / (dt * dt)
        if da > 1.0:
            p[i] = 0.5 * wp.min(p[i], 0.00025) / (dt * dt)
        else:
            p[i] = 0.0
    else:
        da = wp.max(delta, 0.0)
        if cnt_f[i] + cnt_b[i] < 20:
            da = 0.0
        dadv[i] = da
        factor[i] = factor[i] / dt
        if da > 0.0:
            p[i] = 0.5 * wp.min(p[i], 0.5) / dt
        else:
            p[i] = 0.0


@wp.kernel
def pressure_accel(p: wp.array(dtype=float), state: wp.array(dtype=int), nn_f: wp.array2d(dtype=int),
                   cnt_f: wp.array(dtype=int), gw_f: wp.array2d(dtype=wp.vec3), nn_b: wp.array2d(dtype=int),
                   cnt_b: wp.array(dtype=int), gw_b: wp.array2d(dtype=wp.vec3), vb: wp.array(dtype=float), vol: float,
                   eps: float, acc: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    ai = wp.vec3(0.0, 0.0, 0.0)
    if state[i] == 0:
        pi = p[i]
        for k in range(cnt_f[i]):
            ai -= vol * gw_f[i, k] * (pi + p[nn_f[i, k]])
        if wp.abs(pi) > eps:
            for k in range(cnt_b[i]):
                ai += -gw_b[i, k] * (vb[nn_b[i, k]] * pi)
    acc[i] = ai


@wp.kernel
def pressure_iter(acc: wp.array(dtype=wp.vec3), dadv: wp.array(dtype=float), factor: wp.array(dtype=float),
                  state: wp.array(dtype=int), nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int),
                  gw_f: wp.array2d(dtype=wp.vec3), nn_b: wp.array2d(dtype=int), cnt_b: wp.array(dtype=int),
                  gw_b: wp.array2d(dtype=wp.vec3), vb: wp.array(dtype=float), vol: float, dt_pow: float, mode: int,
                  rho0: float, p: wp.array(dtype=float), err: wp.array(dtype=float)):
    i = wp.tid()
    if mode == 0 and state[i] != 0:
        err[i] = 0.0
        return
    ai = acc[i]
    aij_pj = float(0.0)
    for k in range(cnt_f[i]):
        aij_pj += wp.dot(ai - acc[nn_f[i, k]], vol * gw_f[i, k])
    for k in range(cnt_b[i]):
        aij_pj += vb[nn_b[i, k]] * wp.dot(ai, gw_b[i, k])
    aij_pj *= dt_pow
    s_i = float(0.0)
    if mode == 0:
        s_i = 1.0 - dadv[i]
    else:
        s_i = -dadv[i]
    residuum = wp.min(s_i - aij_pj, 0.0)
    if mode == 1 and cnt_f[i] + cnt_b[i] < 20:
        residuum = 0.0
    p[i] = wp.max(p[i] - 0.5 * (s_i - aij_pj) * factor[i], 0.0)
    err[i] = -rho0 * residuum


@wp.kernel
def add_scaled(v: wp.array(dtype=wp.vec3), a: wp.array(dtype=wp.vec3), s: float):
    i = wp.tid()
    v[i] = v[i] + s * a[i]


@wp.kernel
def add_scaled_active(v: wp.array(dtype=wp.vec3), a: wp.array(dtype=wp.vec3), s: float, state: wp.array(dtype=int)):
    i = wp.tid()
    if state[i] == 0:
        v[i] = v[i] + s * a[i]


@wp.kernel
def scale(a: wp.array(dtype=float), s: float):
    i = wp.tid()
    a[i] = a[i] * s


@wp.kernel
def scale_vec(a: wp.array(dtype=wp.vec3), s: float):
    i = wp.tid()
    a[i] = a[i] * s


@wp.kernel
def clear_accel(a: wp.array(dtype=wp.vec3), state: wp.array(dtype=int), g: wp.vec3):
    i = wp.tid()
    if state[i] == 0:
        a[i] = g
    else:
        a[i] = wp.vec3(0.0, 0.0, 0.0)


@wp.kernel
def vmax2(v: wp.array(dtype=wp.vec3), out: wp.array(dtype=float)):
    i = wp.tid()
    wp.atomic_max(out, 0, wp.dot(v[i], v[i]))


@wp.kernel
def nonfinite(x: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3), out: wp.array(dtype=int)):
    i = wp.tid()
    s = x[i][0] + x[i][1] + x[i][2] + v[i][0] + v[i][1] + v[i][2]
    if s != s or wp.abs(s) > 1.0e30:
        out[0] = 1


# ---- Jeske 2023 implicit surface tension (fluid-fluid cohesion; Akinci boundary terms are empty in 2.19) --------
@wp.kernel
def st_grad_rho(v: wp.array(dtype=wp.vec3), nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int),
                gw_f: wp.array2d(dtype=wp.vec3), mass: float, grad_rho: wp.array(dtype=float)):
    i = wp.tid()
    vi = v[i]
    g = float(0.0)
    for k in range(cnt_f[i]):
        g += mass * wp.dot(vi - v[nn_f[i, k]], gw_f[i, k])
    grad_rho[i] = g


@wp.func
def st_first_order(w: float, gw: wp.vec3, d: wp.vec3, dvi: wp.vec3, dvj: wp.vec3, rho_i: float, rho_j: float,
                   gr_i: float, gr_j: float, dt: float, w_min: float, diam2: float) -> float:
    w_coh = (10.0 / 7.0) * wp.min(w, w_min)
    gw_coh = wp.vec3(0.0, 0.0, 0.0)
    if wp.dot(d, d) > diam2:
        gw_coh = gw * (10.0 / 7.0)
    rhoij = rho_i + rho_j
    return 2.0 / rhoij * (w_coh + dt * (wp.dot(gw_coh, dvi - dvj) - w_coh * (gr_i + gr_j) / rhoij))


@wp.kernel
def st_rhs(x: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3), rho: wp.array(dtype=float),
           grad_rho: wp.array(dtype=float), nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int),
           w_f: wp.array2d(dtype=float), gw_f: wp.array2d(dtype=wp.vec3), vdiff: wp.array(dtype=wp.vec3), dt: float,
           cohesion: float, w_min: float, diam2: float, b: wp.array(dtype=wp.vec3), g: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    xi = x[i]
    vi = v[i]
    rho_i = rho[i]
    gr_i = grad_rho[i]
    bi = wp.vec3(0.0, 0.0, 0.0)
    for k in range(cnt_f[i]):
        j = nn_f[i, k]
        d = xi - x[j]
        wf = st_first_order(w_f[i, k], gw_f[i, k], d, vi, v[j], rho_i, rho[j], gr_i, grad_rho[j], dt, w_min, diam2)
        bi += d * (cohesion * rho_i * wf)
    b[i] = vi - (dt / rho_i) * bi
    g[i] = vi + vdiff[i]


@wp.kernel
def st_matvec(vec: wp.array(dtype=wp.vec3), x: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3),
              rho: wp.array(dtype=float), grad_rho: wp.array(dtype=float), nn_f: wp.array2d(dtype=int),
              cnt_f: wp.array(dtype=int), w_f: wp.array2d(dtype=float), gw_f: wp.array2d(dtype=wp.vec3), dt: float,
              cohesion: float, w_min: float, diam2: float, out: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    xi = x[i]
    vi = vec[i]
    vi_old = v[i]
    rho_i = rho[i]
    gr_i = grad_rho[i]
    ai = wp.vec3(0.0, 0.0, 0.0)
    for k in range(cnt_f[i]):
        j = nn_f[i, k]
        d = xi - x[j]
        wf = st_first_order(w_f[i, k], gw_f[i, k], d, vi_old, v[j], rho_i, rho[j], gr_i, grad_rho[j], dt, w_min, diam2)
        ai -= (vi - vec[j]) * (dt * cohesion * rho_i * wf)
    out[i] = vi - (dt / rho_i) * ai


# ---- Weiler 2018 implicit viscosity ------------------------------------------------------------------------------
@wp.kernel
def visc_diag(x: wp.array(dtype=wp.vec3), rho: wp.array(dtype=float), nn_f: wp.array2d(dtype=int),
              cnt_f: wp.array(dtype=int), gw_f: wp.array2d(dtype=wp.vec3), nn_b: wp.array2d(dtype=int),
              cnt_b: wp.array(dtype=int), gw_b: wp.array2d(dtype=wp.vec3), xb: wp.array(dtype=wp.vec3),
              vb: wp.array(dtype=float), mass: float, dt: float, d_mu: float, d_mub: float, h2_001: float, rho0: float,
              inv_diag: wp.array(dtype=wp.mat33)):
    i = wp.tid()
    xi = x[i]
    rho_i = rho[i]
    res = wp.mat33(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    for k in range(cnt_f[i]):
        j = nn_f[i, k]
        d = xi - x[j]
        res += wp.outer(gw_f[i, k], d) * (d_mu * (mass / rho[j]) / (wp.dot(d, d) + h2_001))
    if d_mub != 0.0:
        for k in range(cnt_b[i]):
            j = nn_b[i, k]
            d = xi - xb[j]
            res += wp.outer(gw_b[i, k], d) * (d_mub * (rho0 * vb[j] / rho_i) / (wp.dot(d, d) + h2_001))
    m = wp.identity(n=3, dtype=float) - (dt / rho_i) * res
    inv_diag[i] = wp.inverse(m)


@wp.kernel
def visc_rhs(x: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3), rho: wp.array(dtype=float),
             nn_b: wp.array2d(dtype=int), cnt_b: wp.array(dtype=int), gw_b: wp.array2d(dtype=wp.vec3),
             xb: wp.array(dtype=wp.vec3), velb: wp.array(dtype=wp.vec3), vb: wp.array(dtype=float),
             vdiff: wp.array(dtype=wp.vec3), dt: float, d_mub: float, h2_001: float, rho0: float,
             b: wp.array(dtype=wp.vec3), g: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    xi = x[i]
    vi = v[i]
    rho_i = rho[i]
    bi = wp.vec3(0.0, 0.0, 0.0)
    if d_mub != 0.0:
        for k in range(cnt_b[i]):
            j = nn_b[i, k]
            d = xi - xb[j]
            bi += gw_b[i, k] * (d_mub * (rho0 * vb[j] / rho_i) * wp.dot(velb[j], d) / (wp.dot(d, d) + h2_001))
    b[i] = vi - (dt / rho_i) * bi
    g[i] = vi + vdiff[i]


@wp.kernel
def visc_matvec(vec: wp.array(dtype=wp.vec3), x: wp.array(dtype=wp.vec3), rho: wp.array(dtype=float),
                nn_f: wp.array2d(dtype=int), cnt_f: wp.array(dtype=int), gw_f: wp.array2d(dtype=wp.vec3),
                nn_b: wp.array2d(dtype=int), cnt_b: wp.array(dtype=int), gw_b: wp.array2d(dtype=wp.vec3),
                xb: wp.array(dtype=wp.vec3), vb: wp.array(dtype=float), mass: float, dt: float, d_mu: float,
                d_mub: float, h2_001: float, rho0: float, out: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    xi = x[i]
    vi = vec[i]
    rho_i = rho[i]
    ai = wp.vec3(0.0, 0.0, 0.0)
    for k in range(cnt_f[i]):
        j = nn_f[i, k]
        d = xi - x[j]
        ai += gw_f[i, k] * (d_mu * (mass / rho[j]) * wp.dot(vi - vec[j], d) / (wp.dot(d, d) + h2_001))
    if d_mub != 0.0:
        for k in range(cnt_b[i]):
            j = nn_b[i, k]
            d = xi - xb[j]
            ai += gw_b[i, k] * (d_mub * (rho0 * vb[j] / rho_i) * wp.dot(vi, d) / (wp.dot(d, d) + h2_001))
    out[i] = vi - (dt / rho_i) * ai


@wp.kernel
def apply_vdiff(a: wp.array(dtype=wp.vec3), vnew: wp.array(dtype=wp.vec3), v: wp.array(dtype=wp.vec3), dt: float,
                vdiff: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    d = vnew[i] - v[i]
    a[i] = a[i] + d * (1.0 / dt)
    vdiff[i] = d


# ---- conjugate gradient pieces (Eigen::ConjugateGradient semantics) ------------------------------------------------
@wp.kernel
def cg_residual(b: wp.array(dtype=wp.vec3), ax: wp.array(dtype=wp.vec3), r: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    r[i] = b[i] - ax[i]


@wp.kernel
def cg_precond_identity(r: wp.array(dtype=wp.vec3), z: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    z[i] = r[i]


@wp.kernel
def cg_precond_block(inv_diag: wp.array(dtype=wp.mat33), r: wp.array(dtype=wp.vec3), z: wp.array(dtype=wp.vec3)):
    i = wp.tid()
    z[i] = inv_diag[i] * r[i]


@wp.kernel
def cg_update_xr(xv: wp.array(dtype=wp.vec3), r: wp.array(dtype=wp.vec3), p: wp.array(dtype=wp.vec3),
                 ap: wp.array(dtype=wp.vec3), abs_new: wp.array(dtype=float), p_ap: wp.array(dtype=float)):
    i = wp.tid()
    alpha = abs_new[0] / p_ap[0]
    xv[i] = xv[i] + alpha * p[i]
    r[i] = r[i] - alpha * ap[i]


@wp.kernel
def cg_update_p(p: wp.array(dtype=wp.vec3), z: wp.array(dtype=wp.vec3), abs_new: wp.array(dtype=float),
                abs_old: wp.array(dtype=float)):
    i = wp.tid()
    beta = abs_new[0] / abs_old[0]
    p[i] = z[i] + beta * p[i]
