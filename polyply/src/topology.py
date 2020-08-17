# Copyright 2020 University of Groningen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Provides a class used to describe a gromacs topology and all assciated data.
"""
import os
from pathlib import Path
from collections import defaultdict
from itertools import combinations
import numpy as np
from vermouth.system import System
from vermouth.forcefield import ForceField
from vermouth.gmx.gro import read_gro
from vermouth.pdb import read_pdb
from .top_parser import read_topology
from .linalg_functions import center_of_geometry

COORD_PARSERS = {"pdb": read_pdb,
                 "gro": read_gro}

def replace_defined_interaction(interaction, defines):
    """
    Given an `interaction` check if parameters
    are defined in a list of defines and replace
    by the corresponding numeric value.

    Parameters
    -----------
    interaction: :tuple:`vermouth.molecule.Interaction`
    defines:  dict
      dictionary of type [define]:value

    Returns
    --------
    interaction
      interaction with replaced defines
    """
    new_parameters = []
    for parameter in interaction.parameters:
        if parameter in defines:
            values = defines[parameter]
            for new_param in values:
                 new_parameters.append(new_param)
        else:
            new_parameters.append(parameter)

    interaction.parameters[:] = new_parameters[:]

    return interaction

def lorentz_berthelot_rule(sig_A, sig_B, eps_A, eps_B):
    """
    Lorentz-Berthelot rules for combining LJ paramters.

    Parameters
    -----------
    sig_A:  float
    sig_B:  float
        input sigma values
    eps_A:  float
    eps_B:  float
        input epsilon values

    Returns
    --------
    float
        sigma
    float
        epsilon
    """
    sig = (sig_A + sig_B)/2.0
    eps = (eps_A * eps_B)**0.5
    return sig, eps

def geometric_rule(C6_A, C6_B, C12_A, C12_B):
    """
    Geometric combination rule for combining
    LJ parameters.

    Parameters:
    -----------
    C6_A:  float
    C6_B:  float
        input C6 values
    C12_A:  float
    C12_B:  float
        input C12 values

    Returns:
    --------
    float
         C6
    float
         C12
    """
    C6 = (C6_A * C6_B)**0.5
    C12 = (C12_A * C12_B)**0.5
    return C6, C12


def find_atoms(molecule, attr, value):
    nodes = []
    for node in molecule.nodes:
        if attr in molecule.nodes[node]:
            if molecule.nodes[node][attr] == value:
                nodes.append(node)

    return nodes

class Topology(System):
    """
    Ties together vermouth molecule definitions, and
    Gromacs topology information.

    Parameters
    ----------
    force_field: :class:`vermouth.forcefield.ForceField`
        A force field object.
    name: str, optional
        The name of the topology.

    Attributes
    ----------
    molecules: list[:class:`~vermouth.molecule.Molecule`]
        The molecules in the system.
    force_field: a :class:`vermouth.forcefield.ForceField`
    nonbond_params: dict
        A dictionary of all nonbonded parameters
    types: dict
        A dictionary of all typed parameter
    defines: list
        A list of everything that is defined
    """

    def __init__(self, force_field, name=None):
        super().__init__(force_field)
        self.name = name
        self.defaults = {}
        self.defines = {}
        self.description = []
        self.atom_types = {}
        self.types = defaultdict(list)
        self.nonbond_params = {}

    def preprocess(self):
        """
        Apply all defaults, generate pairs, convert non-bonded
        units. It performs most of the conversion which otherwise
        is done by grompp.
        """
        self.gen_pairs()
        self.replace_defines()
        # only convert if we not already have sig-eps form
        if self.defaults['comb-rule'] == 1:
           self.convert_nonbond_to_sig_eps()

    def replace_defines(self):
        """
        Replace all interaction paramers with defined parameters.
        """
        # Note that a topology cannot define and generate links so
        # they don't need to be replaced or handled elsewhere
        for block in self.force_field.blocks.values():
            for interactions in block.interactions.values():
                for interaction in interactions:
                    new_interaction = replace_defined_interaction(interaction, self.defines)

    def gen_pairs(self):
        """
        If pairs default is set to yes the non-bond params are
        generated for all pairs according to the combination
        rules. Regardless of if pairs is set or not the self
        interactions from atomtypes are added to `self.nonbond_params`.
        Note that nonbond_params takes precedence over atomtypes and
        generated pairs.
        """
        comb_funcs = {1.0: lorentz_berthelot_rule,
                      2.0: geometric_rule,
                      3.0: lorentz_berthelot_rule}

        comb_rule = comb_funcs[self.defaults["comb-rule"]]

        if self.defaults["gen-pairs"] == "yes":
            for atom_type_A, atom_type_B in combinations(self.atom_types, r=2):
                if frozenset([atom_type_A, atom_type_B]) not in self.nonbond_params:
                    nb1_A = self.atom_types[atom_type_A]["nb1"]
                    nb2_A = self.atom_types[atom_type_A]["nb2"]
                    nb1_B = self.atom_types[atom_type_B]["nb1"]
                    nb2_B = self.atom_types[atom_type_B]["nb2"]
                    nb1, nb2 = comb_rule(nb1_A, nb1_B, nb2_A, nb2_B)
                    self.nonbond_params.update({frozenset([atom_type_A, atom_type_B]):
                                               {"nb1": nb1, "nb2": nb2}})

        for atom_type in self.atom_types:
            if frozenset([atom_type, atom_type]) not in self.nonbond_params:
                nb1 = self.atom_types[atom_type]["nb1"]
                nb2 = self.atom_types[atom_type]["nb2"]
                self.nonbond_params.update({frozenset([atom_type, atom_type]):
                                           {"nb1": nb1, "nb2": nb2}})

    def convert_nonbond_to_sig_eps(self):
        """
        Convert all nonbond_params to sigma epsilon form of the
        LJ potential. Note that this assumes the parameters
        are in A, B form.
        """
        for atom_pair in self.nonbond_params:
            nb1 = self.nonbond_params[atom_pair]["nb1"]
            nb2 = self.nonbond_params[atom_pair]["nb2"]

            if nb2 != 0:
                sig = (nb2/nb1)**(1.0/6.0 )
            else:
                sig = 0

            if nb1 != 0:
                eps = nb1**2.0/(4*nb2)
            else:
                eps = 0

            self.nonbond_params.update({atom_pair: {"nb1": sig, "nb2": eps}})

    def add_positions_from_file(self, path):
        """
        Add positions to topology from coordinate file.
        """
        path = Path(path)
        extension = path.suffix.casefold()[1:]
        reader = COORD_PARSERS[extension]
        molecules = reader(path, exclude=())
        total = 0
        for meta_mol in self.molecules:
            for node in meta_mol.molecule.nodes:
                try:
                   position = molecules.nodes[total]["position"]
                except KeyError:
                   meta_mol.molecule.nodes[node]["build"] = True
                   last_atom = total
                else:
                   meta_mol.molecule.nodes[node]["position"] = position
                   meta_mol.molecule.nodes[node]["build"] = False
                   total += 1
                   last_atom = total

            for node in meta_mol:
                atoms_in_res = find_atoms(meta_mol.molecule, "resid", node+1)
                if last_atom not in atoms_in_res:
                    positions = np.array([meta_mol.molecule.nodes[atom]["position"] for
                                          atom in atoms_in_res])
                    center = center_of_geometry(positions)
                    meta_mol.nodes[node]["position"] = center
                else:
                    break

    def add_positions_from_file_meta(self, path):
        """
        Add positions to topology from coordinate file.
        """
        path = Path(path)
        extension = path.suffix.casefold()[1:]
        reader = COORD_PARSERS[extension]
        molecules = reader(path, exclude=())
        total = 0
        for meta_mol in self.molecules:
            for node in meta_mol.nodes:
                position = molecules.nodes[total]["position"]
                meta_mol.nodes[node]["position"] = position
                total +=1

    def convert_to_vermouth_system(self):
        system = System()
        system.molecules = []
        system.force_field = self.force_field

        for meta_mol in self.molecules:
            system.molecules.append(meta_mol.molecule)

        return system

    def convert_meta_to_vermouth_system(self):
        system = System()
        system.molecules = []
        system.force_field = self.force_field

        for meta_mol in self.molecules:
            for node in meta_mol.nodes:
                meta_mol.nodes[node]["atomname"] = "DUM"

        for meta_mol in self.molecules:
            system.molecules.append(meta_mol)

        return system

    @classmethod
    def from_gmx_topfile(cls, path, name):
        """
        Read a gromacs topology file and return an topology object.

        Parameters
        ----------
        path:  str
           The name of the topology file
        name:  str
           The name of the system
        """
        with open(path, 'r') as _file:
            lines = _file.readlines()

        cwdir = os.path.dirname(path)
        force_field = ForceField(name)
        topology = cls(force_field=force_field, name=name)
        read_topology(lines=lines, topology=topology, cwdir=cwdir)
        return topology
