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
Processor for building systems with more than one molecule
"""
# this processor is not a subclass to the regular processor
# class because it cannot run on a single molecule but needs
# the system information
import itertools
import numpy as np
from tqdm import tqdm
from .random_walk import RandomWalk
from .linalg_functions import u_vect
from .topology import lorentz_berthelot_rule

def _compute_box_size(topology, density):
    total_mass = 0
    for molecule in topology.molecules:
        for node in molecule.nodes:
            if 'mass' in molecule.nodes[node]:
                total_mass += molecule.nodes[node]['mass']
            else:
                total_mass += topology.atom_types['mass']
    print(total_mass)
    # amu -> kg and cm3 -> nm3
    #conversion = 1.6605410*10**-27 * 10**27
    box = (total_mass*1.6605410/density)**(1/3.)
    return box


def _prepare_topology(topology):
    n_atoms = 0
    for molecule in topology.molecules:
         for node in molecule.nodes:
            n_atoms+=1

    # we need globally positions and nodes
    positions = np.ones((n_atoms,3)) * np.inf
    nodes_to_gndx = {}
    atom_types = []

    idx = 0
    mol_count = 0
    for molecule in topology.molecules:
        for node in molecule.nodes:
            if "position" in molecule.nodes:
                positions[idx, :] = molecule.nodes["position"]

            resname = molecule.nodes[node]["resname"]
            atom_types.append(resname)
            nodes_to_gndx[(mol_count, node)] = idx
            idx += 1
        mol_count += 1
    print(len(atom_types))
    inter_matrix = {}
    for res_A, res_B in itertools.combinations(set(atom_types), r=2):
        inter_matrix[frozenset([res_A, res_B])] = lorentz_berthelot_rule(topology.volumes[res_A],
                                                                       topology.volumes[res_B], 1, 1)
    for resname, vdw_radii in topology.molecules[0].volumes.items():
        inter_matrix[frozenset([resname, resname])] = vdw_radii

    return positions, atom_types, nodes_to_gndx, inter_matrix


def _rescale_system(topology, scale_factor, nodes_to_gdx, positions):
    for mol_idx, molecule in enumerate(topology.molecules):
        # this works but only pythin 3.7 because depends on dict order
        if not "position" in molecule.nodes[0]:
            continue
        trans_vect = u_vect(molecule.nodes[0]["position"])*scale_factor
        for node in molecule.nodes:
            if "position" in molecule.nodes[node]:
                curr_pos = molecule.nodes[node]["position"]
                molecule.nodes[node]["position"] = curr_pos + trans_vect
                positions[nodes_to_gdx[(mol_idx, node)]] = curr_pos + trans_vect

        return positions

class BuildSystem():
    """
    Compose a system of molecules according
    to the definitions in the topology file.
    """

    def __init__(self, density, n_grid_points=250, maxiter=80, box_size=None):
        self.density = density
        self.n_grid_points = n_grid_points
        self.maxiter = maxiter
        self.box_size = box_size

    def _handle_random_walk(self, molecule, topology, positions, inter_matrix,
                            nodes_to_gndx, atom_types, mol_idx):
        step_count = 0
        while True:
            start = self.box_grid[np.random.randint(len(self.box_grid), size=3)]
            processor = RandomWalk(positions,
                                   nodes_to_gndx,
                                   atom_types,
                                   inter_matrix,
                                   start=start,
                                   mol_idx=mol_idx,
                                   topology=topology,
                                   maxiter=50,
                                   maxdim=self.maxdim)

            positions, processor.run_molecule(molecule)
            if processor.success:
                return True, positions
            elif step_count == self.maxiter:
                return False, positions
            else:
                step_count += 1

    def _compose_system(self, topology):
        """
        Place the molecules of the system into a box
        and optimize positions to meet density.

        Parameters
        ----------
        topology:  :class:`vermouth.system`
        density: foat
           density of the system in kg/cm3

        Returns
        --------
        system
        """
        self.box_size = 1.2 * _compute_box_size(topology, self.density)
        print(self.box_size)
        #self.box_size = 20
        self.box_grid = np.arange(0, self.box_size, self.box_size/self.n_grid_points)
        self.maxdim = np.array([self.box_size, self.box_size, self.box_size])

        positions, atom_types, nodes_to_gndx, inter_matrix = _prepare_topology(
            topology)

        mol_idx = 0
        pbar = tqdm(total=len(topology.molecules))
        mol_tot = len(topology.molecules)

        while mol_idx < mol_tot:
            molecule = topology.molecules[mol_idx]
            success, new_positions = self._handle_random_walk(molecule,
                                                              topology,
                                                              positions,
                                                              inter_matrix,
                                                              nodes_to_gndx,
                                                              atom_types,
                                                              mol_idx)

            if success:
                positions = new_positions
                mol_idx += 1
                pbar.update(1)
            else:
                scaleing_factor = 1.1 #mol_tot/mol_idx
                print("rescaling system by ", scaleing_factor)
                positions = _rescale_system(topology, scaleing_factor, nodes_to_gndx, positions)
                self.maxdim = self.maxdim * scaleing_factor
                print("done")
        pbar.close()

    def run_system(self, topology):
        """
        Compose a system according to a the system
        specifications and a density value.
        """
        self._compose_system(topology)
        return topology
