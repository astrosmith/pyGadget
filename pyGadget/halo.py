# halo.py
# Jacob Hummel
import os
import numpy
import sqlite3
import analyze
import constants

class Halo(object):
    def __init__(self, snapshot, **kwargs):
        super(Halo, self).__init__()
        self.snapshot = snapshot
        self.r_start = kwargs.pop('r_start', 3.08568e17)
        self.step = kwargs.pop('multiplier', 1.01)

        default = snapshot.sim.plotpath +'/'+ snapshot.sim.name
        if not os.path.exists(default):
            os.makedirs(default)
        dbfile = kwargs.pop('dbfile', default+'/halo.db')
        connection = sqlite3.connect(dbfile)
        self.db = connection.cursor()


    def populate(self):
        haloprops = radial_properties(self.snapshot, self.r_init, self.step)


def radial_properties(snapshot, r_start=3.08568e17, r_multiplier=1.01,
                      n_min=50, verbose=True):
    length_unit = 'cm'
    mass_unit = 'g'
    dm_mass = snapshot.dm.get_masses(mass_unit)
    dm_pos = snapshot.dm.get_coords(length_unit)
    gas_mass = snapshot.gas.get_masses(mass_unit)
    gas_pos = snapshot.gas.get_coords(length_unit)
    dens = snapshot.gas.get_density('cgs')
    temp = snapshot.gas.get_temperature()

    gasx = gas_pos[:,0]
    gasy = gas_pos[:,1]
    gasz = gas_pos[:,2]
    dmx = dm_pos[:,0]
    dmy = dm_pos[:,1]
    dmz = dm_pos[:,2]
    del dm_pos

    mass = numpy.concatenate((gas_mass, dm_mass))
    del gas_mass
    del dm_mass
    x = numpy.concatenate((gasx,dmx))
    y = numpy.concatenate((gasy,dmy))
    z = numpy.concatenate((gasz,dmz))
    del dmx,dmy,dmz

    x,y,z = analyze.find_center(x, y, z, dens, centering='max',
                                centering_verbose=verbose)
    gasx,gasy,gasz = analyze.find_center(gasx,gasy,gasz, dens, centering='max',
                                         centering_verbose=verbose)
    del dens
    del gas_pos
    r = numpy.sqrt(numpy.square(x) + numpy.square(y) + numpy.square(z))
    gasr = numpy.sqrt(numpy.square(gasx)
		      + numpy.square(gasy)
		      + numpy.square(gasz))
    del x,y,z,gasx,gasy,gasz
    
    halo_properties = []
    n = old_n = old_r = density = energy = 0
    # background density:: Omega_m * rho_crit(z)
    background_density = .27 * 9.31e-30 * (1+snapshot.header.Redshift)**3 
    rmax = r_start
    while (density > 180 * background_density or n < n_min):
        inR = numpy.where(r <= rmax)[0]
        gasinR = numpy.where(gasr <= rmax)[0]
        n = inR.size
        if n > old_n:
            inShell = numpy.where(r[inR] > old_r)[0]
            gasinShell = numpy.where(r[gasinR] > old_r)[0]
            rpc = rmax/3.08568e18
            Mtot = mass[inR].sum()
	    Mshell = mass[inShell].sum()
            solar_masses = Mtot/1.989e33
            density = 3 * Mtot / (4*numpy.pi * rmax**3)
            delta = density/background_density
	    tshell = temp[gasinShell].mean()
	    tavg = temp[gasinR].mean()
	    tff = numpy.sqrt(3*numpy.pi/32/constants.GRAVITY/density)
	    cs = numpy.sqrt(constants.k_B * tavg / constants.m_H)
	    Lj = cs*tff
	    Mj = density * (4*numpy.pi/3) * Lj**3 / 1.989e33
	    energy += constants.GRAVITY * Mtot * Mshell / rmax
            if verbose: 
                print 'R = %.2e pc' %rpc,
		print 'Mass enclosed: %.2e' %solar_masses,
                print 'Energy: %.3e' %energy,
                print 'delta: %.3f' %delta
            if delta >= 178.0:
                halo_properties.append((rpc,delta,solar_masses,density,
                                        tavg,tshell,tff,cs,Lj,Mj,-energy,n))
            old_n = n
	    old_r = rmax
        rmax *= r_multiplier
    
    del r
    print 'snapshot', snapshot.number, 'analyzed.'
    return numpy.asarray(halo_properties)

