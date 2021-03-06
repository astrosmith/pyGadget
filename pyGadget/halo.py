# halo.py
# Jacob Hummel
import os
import numpy
import sqlite3
#from numba import autojit

import analyze
import constants

class Halo(object):
    def __init__(self, sim, **kwargs):
        super(Halo, self).__init__()
        self.sim = sim
        default = sim.plotpath +'/'+ sim.name
        if not os.path.exists(default):
            os.makedirs(default)
        dbfile = kwargs.pop('dbfile', default+'/halo.db')
        self.db = sqlite3.connect(dbfile)
        self.c = self.db.cursor()

    def load(self, snap, *hprops):
        fields = ''
        if hprops:
            for hprop in hprops[:-1]:
                fields += hprop + ', '
            fields += hprops[-1]
        else: 
            fields = '*'
        table = 'snapshot{:0>4}'.format(snap)
        try:
            self.c.execute("SELECT " + fields + " FROM " + table)
        except sqlite3.OperationalError:
            print "Warning: Halo data for this snapshot does not exist."
            print "Analyzing..."
            self.populate(snap, verbose=False)
            self.c.execute("SELECT " + fields + " FROM " + table)
            
        self.data = numpy.asarray(self.c.fetchall())

    def populate(self, snap, **kwargs):
        snapshot = self.sim.load_snapshot(snap)
        haloprops = radial_properties(snapshot, **kwargs)
        snapshot.gas.cleanup()
        snapshot.dm.cleanup()
        snapshot.close()
        table = 'snapshot{:0>4}'.format(snap)
        create = ("CREATE TABLE " + table +
                  "(redshift real, radius real, delta real, density real, "\
                  "gas_density real, total_mass real, total_gas real, "\
                  "shell_mass real, shell_gas real, shell_dens real, "\
                  "shell_gdens real, tff real, Tavg real, Tshell real, "\
                  "cs real, cshell real, Lj real, Mj real, gpe real, "\
                  "npart integer)")
        try:
            self.c.execute(create)
        except sqlite3.OperationalError:
            self.c.execute("DROP TABLE " + table)
            self.c.execute(create)
        insert = ("INSERT INTO " + table + "(redshift, radius, delta, "\
                  "density, gas_density, total_mass, total_gas, shell_mass, "\
                  "shell_gas, shell_dens, shell_gdens, tff, Tavg, Tshell, cs, "\
                  "cshell, Lj, Mj, gpe, npart) "\
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        self.c.executemany(insert, haloprops)
        self.db.commit()

#===============================================================================
def radial_properties(snapshot, **kwargs):
    r_start = kwargs.pop('r_start', 3.08568e14)
    r_multiplier = kwargs.pop('multiplier', 1.2)
    verbose = kwargs.pop('verbose', True)
    n_min = kwargs.pop('n_min', 32)

    length_unit = 'cm'
    mass_unit = 'g'

    redshift = snapshot.header.Redshift
    dens = snapshot.gas.get_density('cgs')
    xyz = snapshot.gas.get_coords(length_unit)
    uvw = snapshot.gas.get_velocities()
    center, vcenter = analyze.find_center(xyz[:,0],xyz[:,1],xyz[:,2],
                                          uvw[:,0],uvw[:,1],uvw[:,2],
                                          dens, centering='max')
    gas_pos = snapshot.gas.get_coords(length_unit, system='spherical',
                                      center=center)
    dm_pos = snapshot.dm.get_coords(length_unit, system='spherical',
                                    center=center)
    dm_mass = snapshot.dm.get_masses(mass_unit)
    gas_mass = snapshot.gas.get_masses(mass_unit)
    temp = snapshot.gas.get_temperature()

    gasr = gas_pos[:,0]
    dmr = dm_pos[:,0]
    r = numpy.concatenate((gasr,dmr))
    mass = numpy.concatenate((gas_mass, dm_mass))

    print 'Data loaded.  Analyzing...'
    halo_properties = analyze_halo(redshift, r, gasr, mass, gas_mass, temp,
                                   r_start, r_multiplier, n_min, verbose)
    print 'snapshot', snapshot.number, 'analyzed.'
    return halo_properties

#@autojit
def analyze_halo(redshift, r, gasr, mass, gmass, temp,
                 r_start, r_multiplier, n_min, verbose):
    k_B = 1.3806e-16 # erg/K
    m_H = 1.6726e-24 # g
    GRAVITY = 6.6726e-8 # dyne * cm**2 / g**2
    halo_properties = []
    n = 0
    old_n = 0
    old_r = 0
    density = 0
    energy = 0
    # background density:: Omega_m * rho_crit(z)
    background_density = .27 * 9.31e-30 * (1+redshift)**3 
    rmax = r_start
    while (density > 178 * background_density or n < 100):
        inR = numpy.where(r <= rmax)[0]
        gasinR = numpy.where(gasr <= rmax)[0]
        n = inR.size
        if n > old_n + n_min:
            inShell = numpy.where((r > old_r) & (r <= rmax))[0]
            gasinShell = numpy.where((gasr > old_r) & (gasr <= rmax))[0]
            rpc = rmax/3.08568e18
            Mtot = mass[inR].sum()
            Mshell = mass[inShell].sum()
            Msun = Mtot/1.989e33
            gMtot = gmass[gasinR].sum()
            gMshell = gmass[gasinShell].sum()
            gMsun = gMtot/1.989e33
            density = 3 * Mtot / (4*numpy.pi * rmax**3)
            gdensity = 3 * gMtot / (4*numpy.pi * rmax**3)
            shell_vol = 4/3 * numpy.pi * (rmax**3 - old_r**3)
            rhoShell = Mshell / shell_vol
            grhoShell = gMshell / shell_vol
            delta = density/background_density
            tshell = analyze.reject_outliers(temp[gasinShell]).mean()
            tavg = analyze.reject_outliers(temp[gasinR]).mean()
            tff = numpy.sqrt(3*numpy.pi/32/GRAVITY/density)
            cs = numpy.sqrt(k_B * tavg / m_H)
            cshell = numpy.sqrt(k_B * tshell / m_H)
            Lj = cs*tff
            Mj = density * (4*numpy.pi/3) * Lj**3 / 1.989e33
            energy += GRAVITY * Mtot * Mshell / rmax
            if verbose:
                print 'R = %.2e pc' %rpc,
                print 'Mass enclosed: %.2e' %Msun,
                print 'Energy: %.3e' %energy,
                print 'delta: %.3f' %delta
            halo_properties.append((redshift,rpc,delta,density,gdensity,
                                    Msun,gMsun,Mshell,gMshell,rhoShell,
                                    grhoShell,tff,tavg,tshell,cs,cshell,
                                    Lj,Mj,-energy,n))
            old_n = n
            old_r = rmax
        rmax *= r_multiplier
    return halo_properties
