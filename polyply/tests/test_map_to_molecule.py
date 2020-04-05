# Copyright 2018 University of Groningen
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
Test that force field files are properly read.
"""

import textwrap
import pytest
import numpy as np
import networkx as nx
import vermouth.forcefield
import vermouth.molecule
import polyply.src.meta_molecule
import polyply.src.map_to_molecule
import polyply.src.parsers
from polyply.src.meta_molecule import (MetaMolecule, Monomer)
from vermouth.molecule import Interaction

class TestMapToMolecule:
    @staticmethod
    def test_add_blocks():
        lines = """
        [ moleculetype ]
        ; name nexcl.
        PEO         1
        ;
        [ atoms ]
        1  SN1a    1   PEO   CO1  1   0.000  45
        2  SN1a    1   PEO   CO2  1   0.000  45
        3  SN1a    1   PEO   CO3  1   0.000  45
        4  SN1a    1   PEO   CO4  1   0.000  45
        [ bonds ]
        ; back bone bonds
        1  2   1   0.37 7000
        2  3   1   0.37 7000
        2  4   1   0.37 7000
        4  5   1   0.37 7000
        """
        lines = textwrap.dedent(lines).splitlines()
        ff = vermouth.forcefield.ForceField(name='test_ff')
        polyply.src.parsers.read_polyply(lines, ff)
        meta_mol = MetaMolecule(name="test", force_field=ff)
        meta_mol.add_monomer(0,"PEO",[])
        meta_mol.add_monomer(1,"PEO",[(1,0)])
        new_meta_mol = polyply.src.map_to_molecule.MapToMolecule().run_molecule(meta_mol)

        bonds = [Interaction(atoms=(0, 1), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(1, 2), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(1, 3), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(4, 5), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(5, 6), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(5, 7), parameters=['1', '0.37', '7000'], meta={})]

        assert new_meta_mol.molecule.interactions['bonds'] == bonds

    @staticmethod
    def test_multiresidue_block():
        lines = """
        [ moleculetype ]
        ; name nexcl.
        PEO         1
        ;
        [ atoms ]
        1  SN1a    1   PEO   CO1  1   0.000  45
        [ moleculetype ]
        ; name nexcl.
        MIX         1
        ;
        [ atoms ]
        1  SN1a    1   R1   C1  1   0.000  45
        2  SN1a    1   R1   C2  1   0.000  45
        3  SC1     2   R2   C1  2   0.000  45
        4  SC1     2   R2   C2  2   0.000  45
        [ bonds ]
        ; back bone bonds
        1  2   1   0.37 7000
        2  3   1   0.37 7000
        3  4   1   0.37 7000
        """
        lines = textwrap.dedent(lines).splitlines()
        ff = vermouth.forcefield.ForceField(name='test_ff')
        polyply.src.parsers.read_polyply(lines, ff)
        meta_mol = MetaMolecule(name="test", force_field=ff)
        meta_mol.add_monomer(0,"PEO",[])
        meta_mol.add_monomer(1,"MIX",[(1,0)])

        new_meta_mol = polyply.src.map_to_molecule.MapToMolecule().run_molecule(meta_mol)

        bonds = [Interaction(atoms=(1, 2), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(2, 3), parameters=['1', '0.37', '7000'], meta={}),
                 Interaction(atoms=(3, 4), parameters=['1', '0.37', '7000'], meta={})]

        edges = [(0,1), (1,2)]

        assert new_meta_mol.molecule.interactions['bonds'] == bonds
        assert len(new_meta_mol.nodes) == 3
        assert list(new_meta_mol.edges) == edges
        assert nx.get_node_attributes(new_meta_mol, "resname") == {0: "PEO", 1: "R1", 2: "R2"}