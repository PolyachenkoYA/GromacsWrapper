# $Id$
"""
Setting up a Gromacs MD run
===========================

Individual steps such as solvating a structure or energy minimization
are set up in individual directories. For energy minimization one
should supply appropriate mdp run input files; otherwise example
templates are used.


:Functions:

  topology:         generate initial topology file (NOT WORKING)
  solvate:          solvate globular protein and add ions to neutralize
  energy_minimize:  set up energy minimization and run it (using ``mdrun_d``)
  MD_restrained:    set up restrained MD
  MD:               set up equilibrium MD

:Note:

- **This is software is in ALPHA status and likely to change
    completely in the future.**

- You **must** check all simulation parameters for yourself. Do not
  rely on any defaults provided here.

"""

from __future__ import with_statement
import os
import errno
import re
import shutil
from contextlib import contextmanager

from pkg_resources import resource_filename


import gromacs
import gromacs.cbook

@contextmanager
def in_dir(directory):
    """Context manager to execute a code block in a directory.

    * directory is created if it does not exist
    * at the end or after and exception code always returns to
      the directory that was the current directory before entering
      the block
    """
    startdir = os.getcwd()
    try:
        try:
            os.chdir(directory)
        except OSError, err:
            if err.errno == errno.ENOENT:
                os.makedirs(directory)
                os.chdir(directory)
            else:
                raise
        yield os.getcwd()
    finally:
        os.chdir(startdir)

# TODO:
# - should be part of a class so that we can store the topology etc
# - full logging would be nice (for provenance)

def topology(struct=None, protein='protein',
             ff='oplsaa', watermodel='TIP4P', 
             top='system.top',  dirname='top'):
    """Build Gromacs topology files from pdb.
    
    INCOMPLETE
    """
    raise NotImplemented('sorry, this needs to be done manually at the moment')

    structure = os.path.realpath(struct)
    topology = os.path.realpath(os.path.join(dirname, top))
    
    new_struct = protein + '.pdb'
    posres = protein + '_posres.itp'

    with in_dir(dirname):
        gromacs.pdb2gmx(ff=ff, water=watermodel, f=structure,
                        o=new_struct, p='tmp', i=posres)
        # need some editing  protein_tmp --> system.top and protein.itp

    return topology, new_struct

def solvate(struct='top/protein.pdb', top='top/system.top',
            distance=0.9, boxtype='dodecahedron',
            concentration=0, cation='NA+', anion='CL-',
            dirname='solvate'):
    """Put protein into box, add water, add ions."""

    structure = os.path.realpath(struct)
    topology = os.path.realpath(top)

    # should scrub topology but hard to know what to scrub; for
    # instance, some ions or waters could be part of the crystal structure
    
    with in_dir(dirname):
        gromacs.editconf(f=structure, o='boxed.gro', bt=boxtype, d=distance)
        gromacs.genbox(p=topology, cp='boxed.gro', cs='tip4p', o='solvated.gro')

        with open('none.mdp','w') as mdp:
            print >> mdp, '; empty'

        qtot = gromacs.cbook.grompp_qtot(f='none.mdp', o='topol.tpr', c='solvated.gro',
                                         p=topology, stdout=False)
        print "After solvation: total charge qtot = %(qtot)r" % vars()        

        # TODO:
        # - get number of waters <---- ! hold up (grep topol...)
        # - calculate numbers from concentration
        # target concentration of free ions: c = 100mM  (c_water = 55M)
        # N = N_water * c/c_water
        # add ions for concentration to the counter ions (counter ions are less free)
        if concentration != 0:
            raise NotImplementedError('only conc = 0 working at moment')

        # neutralize (or try -neutral switch of genion)
        n_cation = n_anion = 0
        if qtot > 0:
            n_anion = int(abs(qtot))
        elif qtot < 0:
            n_cation = int(abs(qtot))
        gromacs.genion(s='topol.tpr', o='ionized.gro', p=topology,
                       pname=cation, nname=anion, np=n_cation, nn=n_anion,
                       input='SOL')

        qtot = gromacs.cbook.grompp_qtot(f='none.mdp', o='ionized.tpr', c='ionized.gro',
                                         p=topology, stdout=False)
        gromacs.cbook.trj_compact(f='ionized.gro', s='ionized.tpr', o='compact.pdb')
        return qtot

# templates have to be extracted from the egg because they are used
# by external code
templates = {'em_mdp': resource_filename(__name__, 'templates/em.mdp'),
             'md_mdp': resource_filename(__name__, 'templates/md.mdp'),
             'deathspud_sge': resource_filename(__name__, 'templates/deathspud.sge'),
             'neuron_sge': resource_filename(__name__, 'templates/neuron.sge'),
             }
sge_template = templates['neuron_sge']

def energy_minimize(dirname='em', mdp=templates['em_mdp'],
                    struct='solvate/ionized.gro', top='top/system.top',
                    **mdp_kwargs):
    """Energy minimize the system.

    energy_minimize(**kwargs)

    This sets up the system (creates run input files) and also runs
    ``mdrun_d``. Thus it can take a while.

    Many of the keyword arguments below already have sensible values. 

    :Keyword arguments:

    dirname        set up under directory dirname [em]
    struct         input structure (gro, pdb, ...) [solvate/ionized.gro]
    top            topology file [top/system.top]
    mdp            mdp file (or use the template) [templates/em.mdp]

    **mdp_kwargs   dictionary of values that should be changed in the 
                   template mdp file, eg {'nstxtcout': 250, 'nstfout': 250}

    :Bugs & Limitations:

    * If ``mdrun_d`` is not found, it fails with OSError.
    """

    structure = os.path.realpath(struct)
    topology = os.path.realpath(top)
    mdp_template = os.path.realpath(mdp)    
    mdp = 'em.mdp'
    tpr = 'em.tpr'

    with in_dir(dirname):
        gromacs.cbook.edit_mdp(mdp_template, new_mdp=mdp, **mdp_kwargs)
        gromacs.grompp(f=mdp, o=tpr, c=structure, p=topology, maxwarn=1)
        # TODO: not clear yet how to run as MPI with mpiexec & friends
        # TODO: fall back to mdrun wif no double precision binary
        gromacs.mdrun_d('v', stepout=10, deffnm='em', c='em.pdb')   # or em.pdb ? (box??)
        # em.gro --> gives 'Bad box in file em.gro' warning ??


def _setup_MD(dirname,
              deffnm='md', mdp=templates['md_mdp'],
              struct=None,
              top='top/system.top', ndx=None,
              sge=sge_template,
              dt=0.002, runtime=1e3, **mdp_kwargs):

    if struct is None:
        raise ValueError('struct must be set to a input structure')
    structure = os.path.realpath(struct)
    topology = os.path.realpath(top)
    mdp_template = os.path.realpath(mdp)
    sge_template = os.path.realpath(sge)

    nsteps = int(float(runtime)/float(dt))

    mdp = deffnm + '.mdp'
    tpr = deffnm + '.tpr'

    mdp_parameters = {'nsteps':nsteps, 'dt':dt}
    mdp_parameters.update(mdp_kwargs)
    
    with in_dir(dirname):
        # do I need an index file?
        gromacs.cbook.edit_mdp(mdp_template, new_mdp=mdp, 
                               **mdp_parameters)
        gromacs.grompp(f=mdp, p=topology, c=structure, n=ndx, o=tpr)
        # edit sge script manually
        # TODO: edit DEFFNM in sge template
        shutil.copy(sge_template, os.path.curdir)        

    print "All files set up for a run time of %(runtime)g ps "\
        "(dt=%(dt)g, nsteps=%(nsteps)g)" % vars()
    return {'dirname':dirname, 'tpr':tpr}


def MD_restrained(dirname='MD_POSRES', **kwargs):
    """Set up MD with position restraints.

    MD_restrained(**kwargs)

    Many of the keyword arguments below already have sensible values. 

    :Keyword arguments:

    dirname        set up under directory dirname [MD_POSRES]
    struct         input structure (gro, pdb, ...) [em/em.pdb]
    top            topology file [top/system.top]
    mdp            mdp file (or use the template) [templates/md.mdp]
    deffnm         default filename for Gromacs run [md]
    runtime        total length of the simulation in ps [1e3]
    dt             integration time step in ps [0.002]
    sge            script to submit to the SGE queuing system

    **mdp_kwargs   dictionary of values that should be changed in the 
                   template mdp file, eg {'nstxtcout': 250, 'nstfout': 250}
    """

    kwargs.setdefault('struct', 'em/em.pdb')
    kwargs['define'] = '-DPOSRES'
    return _setup_MD(dirname, **kwargs)

def MD(dirname='MD', **kwargs):
    """Set up equilibrium MD.

    MD(**kwargs)

    Many of the keyword arguments below already have sensible values. 

    :Keyword arguments:

    dirname        set up under directory dirname [MD]
    struct         input structure (gro, pdb, ...) [MD_POSRES/md_posres.pdb]
    top            topology file [top/system.top]
    mdp            mdp file (or use the template) [templates/md.mdp]
    deffnm         default filename for Gromacs run [md]
    runtime        total length of the simulation in ps [1e3]
    dt             integration time step in ps [0.002]
    sge            script to submit to the SGE queuing system

    **mdp_kwargs   dictionary of values that should be changed in the 
                   template mdp file, eg {'nstxtcout': 250, 'nstfout': 250}
    """

    kwargs.setdefault('struct', 'MD_POSRES/md_posres.pdb')
    return _setup_MD(dirname, **kwargs)



# TODO: autorun (qv MI lipids/setup.pl)
