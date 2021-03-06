# sim.py
# Jacob Hummel
import os
import glob
import numpy
import subprocess
import threading
import Queue
import multiprocessing as mp

import sink
import units
import snapshot
import plotting

class Simulation(object):
    """
    Class for simulations.  Primarily for gathering metadata such as file
    paths and unit coversions.
    """
    def __init__(self, sim_name, **simargs):
        super(Simulation,self).__init__()
        self.name = sim_name
        self.filepath = simargs.pop('path',os.getenv('HOME')+'/sim/')
        self.datapath = simargs.pop('datapath',os.getenv('HOME')+'/data/')
        self.sinkpath = simargs.pop('sinkpath',
                                    os.getenv('HOME') + '/data/sinks/')
        self.plotpath = simargs.pop('plotpath',
                                    os.getenv('HOME') + '/data/simplots/')
        self.set_field_names(simargs.pop('field_names',{}))
                                     
        self.refine_gas = simargs.pop('refine_gas', False)
        self.refine_nbody = simargs.pop('refine_nbody', False)

        self.sink_tracking = simargs.pop('track_sinks', False)
        self.coordinates = simargs.pop('coordinates', 'physical')
        self.batch_viewscale = None

        self.units = units.Units(**simargs)
        self.units.set_coordinate_system(self.coordinates)

        self.snapfiles = self.find_snapshots()
        self.track_sinks(self.sink_tracking)

    def set_field_names(self, name_dict={}):
        self.hdf5_fields = {'particleIDs':'ParticleIDs',
                            'masses':'Masses',
                            'coordinates':'Coordinates',
                            'velocities':'Velocities',
                            'smoothing_length':'SmoothingLength',
                            'density':'Density',
                            'internal_energy':'InternalEnergy',
                            'adiabatic_index':'Adiabatic index',
                            'abundances':'ChemicalAbundances',
                            'sink_value':'SinkValue'}
        self.hdf5_fields.update(name_dict)
        self._internal_fields = {v:k for k,v in self.hdf5_fields.items()}

    def track_sinks(self, boolean=True):
        self.sink_tracking = boolean
        self.tsink = None
        if self.sink_tracking:
            try:
                self.sink1 = sink.SinkHistory(self.sinkpath + self.name)
                print "Found sinkfiles.  Loading sinkdata."
                self.tsink = self.sink1.time[0]
            except IOError:
                pass
            if self.tsink:
                self.sinks = [self.sink1]
                nsinks = self.sink1.all_ids.size
                if nsinks > 1:
                    for i in range(2,nsinks+1):
                        s = sink.SinkHistory(self.sinkpath+self.name, i)
                        vars(self)['sink'+str(i)] = s
                        self.sinks.append(s)

    def refine_by_mass(self, boolean=True):
        self.refine_gas = boolean
        self.refine_nbody = boolean

    def set_coordinate_system(self,coordinates):
        self.units.set_coordinate_system(coordinates)
        self.coordinates = self.units.coordinate_system

    def set_batch_viewscale(self, scale):
        unit = "".join(ch if not ch.isdigit() else "" for ch in scale)
        if unit in self.units.lengths.keys():
            self.batch_viewscale = scale
        else:
            raise KeyError

    def find_snapshots(self, *nums):
        path = self.filepath + self.name
        files0 = glob.glob(path+'/snapshot_???.hdf5')
        files1 = glob.glob(path+'/snapshot_????.hdf5')
        files0.sort()
        files1.sort()
        files = files0 + files1
        snapfiles = {}
        for f in files:
            num = int(f[:-5].split('_')[-1])
            if nums:
                if num in nums:
                    snapfiles[num] = f
            else:
                snapfiles[num] = f
        return snapfiles

    def set_snapshots(self, *nums):
        self.snapfiles = self.find_snapshots(*nums)

    def load_snapshot(self, num, *load_keys,**kwargs):
        if ((kwargs.pop('track_sinks',False)) or self.sink_tracking):
            kwargs['track_sinks'] = True
        if ((kwargs.pop('refine_gas',False)) or self.refine_gas):
            kwargs['refine_gas'] = True
        if ((kwargs.pop('refine_nbody',False)) or self.refine_nbody):
            kwargs['refine_nbody'] = True

        try:
            fname = self.snapfiles[num]
        except KeyError:
            try:
                fname = self.find_snapshots(num)[num]
            except KeyError:
                raise IOError('Sim ' + self.name + ' snapshot '
                              + str(num) + ' not found!')
        snap = snapshot.File(self, fname, **kwargs)

        if kwargs.get('track_sinks', False):
            if snap.gas._sink_indices.size > 0:
                if snap.sim.tsink is None:
                    snap.sim.tsink = snap.header.Time * units.Time_yr

        if load_keys:
            snap.gas.load_data(*load_keys,**kwargs)
        else:
            snap.gas.cleanup()
        return snap

    def multitask(self, task, *data, **kwargs):
        maxprocs = mp.cpu_count() - 1
        file_queue = mp.Queue()
        data_queue = mp.Queue(maxprocs/4)
        loader = snapshot.Loader(self.load_snapshot, file_queue, data_queue)
        loader.start()
        snaps = self.snapfiles.keys()
        snaps.sort()
        for snap in snaps:
            args = (snap,)+data
            file_queue.put(args)
        for i in range(maxprocs):
            file_queue.put(None)

        jobs = []
        if kwargs.pop('parallel', True):
            for i in range(maxprocs):
                p = mp.Process(target=self.controller,
                               args=(task,data_queue))
                p.start()
                jobs.append(p)
            for process in jobs:
                process.join()

        else:
            file_queue.put(None)
            self.controller(task, data_queue)

    def controller(self, task, data_queue):
        print "Starting compute process..."
        done = False
        while not done:
            try:
                snap = data_queue.get()
            except Queue.Empty:
                break
            if snap is None:
                done = True
                break
            else:
                wp = self.plotpath + self.name
                task(snap, wp)
        print "Compute process complete."

#===============================================================================
class Loader(threading.Thread):
    def __init__(self, load_function, file_queue, data_queue):
        self.file_queue = file_queue
        self.data_queue = data_queue
        self.load_function = load_function
        threading.Thread.__init__(self)

    def run(self):
        lock = threading.Lock()
        while 1:
            try:
                args = self.file_queue.get(timeout=1)
            except Queue.Empty:
                break # reached end of queue
            if args is None:
                self.data_queue.put(None)
            else:
                fname = args[0]
                lock.acquire()
                print 'loading snapshot', fname
                lock.release()
                try:
                    snapshot = self.load_function(*args)
                    snapshot.close()
                    self.data_queue.put(snapshot)
                except IOError:
                    lock.acquire()
                    print 'Warning: snapshot '+str(fname)+' not found!'
                    lock.release()
                    pass
