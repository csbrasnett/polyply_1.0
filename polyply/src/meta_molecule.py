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
from collections import (namedtuple, OrderedDict)
import json
import networkx as nx
from networkx.readwrite import json_graph
from vermouth.graph_utils import make_residue_graph
from .polyply_parser import read_polyply
from tqdm import tqdm

Monomer = namedtuple('Monomer', 'resname, n_blocks')

def find_atoms(molecule, attr, value):
    """
    Find all nodes of a `vermouth.molecule.Molecule` that have the
    attribute `attr` with the corresponding value of `value`.

    Parameters
    ----------
    molecule: :class:vermouth.molecule.Molecule
    attr: str
         attribute that a node needs to have
    value:
         corresponding value

    Returns
    ----------
    list
       list of nodes found
    """
    nodes = []
    for node in molecule.nodes:
        if attr in molecule.nodes[node] and molecule.nodes[node][attr] == value:
            nodes.append(node)

    return nodes


def _make_edges(force_field):
    for block in force_field.blocks.values():
        inter_types = list(block.interactions.keys())
        for inter_type in inter_types:
            block.make_edges_from_interaction_type(type_=inter_type)

    for link in force_field.links:
        inter_types = list(link.interactions.keys())
        for inter_type in inter_types:
            link.make_edges_from_interaction_type(type_=inter_type)

class MetaMolecule(nx.Graph):
    """
    Graph that describes molecules at the residue level.
    """

    node_dict_factory = OrderedDict

    def __init__(self, *args, **kwargs):
        self.force_field = kwargs.pop('force_field', None)
        super().__init__(*args, **kwargs)
        self.molecule = None

    def add_monomer(self, current, resname, connections):
        """
        This method adds a single node and an unlimeted number
        of edges to an instance of :class::`MetaMolecule`. Note
        that matches may only refer to already existing nodes.
        But connections can be an empty list.
        """
        self.add_node(current, resname=resname)
        for edge in connections:
            if self.has_node(edge[0]) and self.has_node(edge[1]):
                self.add_edge(edge[0], edge[1])
            else:
                msg = ("Edge {} referes to nodes that currently do"
                       "not exist. Cannot add edge to unkown nodes.")
                raise IOError(msg.format(edge))

    def split_residue(self, split_string, max_resid):
        """
        split_string RESNAME:NEW_RESNAME-ATOMS
        """
        resname = split_string.split(":")[0]
        new_residues = split_string.split(":")[1:]

        self.old_resids = nx.get_node_attributes(self.molecule, "resid")
        self.old_resnames = nx.get_node_attributes(self.molecule, "resname")

        for node in self.nodes:
            old_resid = self.nodes[node]["resid"]
            if self.nodes[node]["resname"] == resname:
                old_atoms = find_atoms(self.molecule, "resid", old_resid)
                atom_names = {self.molecule.nodes[atom]["atomname"]:atom for atom in old_atoms}
                for new_res in new_residues:
                    new_name, atoms = new_res.split("-")
                    names = atoms.split(",")
                    for atom in names:
                        try:
                            node_key = atom_names[atom]
                        except KeyError:
                            msg = ("Residue {} {} has no atom {}.")
                            raise IOError(msg.format(resname, old_resid, atom))
                        self.molecule.nodes[node_key]["resname"] = new_name
                        self.molecule.nodes[node_key]["resid"] = max_resid + 1
                    max_resid += 1

        print("making residue graph")
        new_meta_graph = make_residue_graph(self.molecule, attrs=('resid', 'resname'))
        self.clear()
        self.add_nodes_from(new_meta_graph.nodes(data=True))
        self.add_edges_from(new_meta_graph.edges)
        return max_resid

    def get_edge_resname(self, edge):
        return [self.nodes[edge[0]]["resname"], self.nodes[edge[1]]["resname"]]

    @staticmethod
    def _block_graph_to_res_graph(block):
        """
        generate a residue graph from the nodes of `block`.

        Parameters
        -----------
        block: `:class:vermouth.molecule.Block`

        Returns
        -------
        :class:`nx.Graph`
        """
        res_graph = make_residue_graph(block, attrs=('resid', 'resname'))
        return res_graph

    @classmethod
    def from_monomer_seq_linear(cls, force_field, monomers, mol_name):
        """
        Constructs a meta graph for a linear molecule
        which is the default assumption from
        """

        meta_mol_graph = cls(force_field=force_field, name=mol_name)
        res_count = 0

        for monomer in monomers:
            trans = 0
            while trans < monomer.n_blocks:

                if res_count != 0:
                    connect = [(res_count-1, res_count)]
                else:
                    connect = []
                trans += 1

                meta_mol_graph.add_monomer(res_count, monomer.resname, connect)
                res_count += 1
        return meta_mol_graph

    @classmethod
    def from_json(cls, force_field, json_file, mol_name):
        """
        Constructs a :class::`MetaMolecule` from a json file
        using the networkx json package.
        """
        with open(json_file) as file_:
            data = json.load(file_)

        init_graph = nx.Graph(json_graph.node_link_graph(data))
        graph = nx.Graph(node_dict_factory=OrderedDict)
        nodes = list(init_graph.nodes)
        nodes.sort()

        for node in nodes:
            attrs = init_graph.nodes[node]
            graph.add_node(node, **attrs)

        graph.add_edges_from(init_graph.edges)
        meta_mol = cls(graph, force_field=force_field, mol_name=mol_name)
        return meta_mol

    @classmethod
    def from_itp(cls, force_field, itp_file, mol_name):
        """
        Constructs a :class::`MetaMolecule` from an itp file.
        """
        with open(itp_file) as file_:
            lines = file_.readlines()
            read_polyply(lines, force_field)

        graph = MetaMolecule._block_graph_to_res_graph(force_field.blocks[mol_name])
        meta_mol = cls(graph, force_field=force_field, mol_name=mol_name)
        meta_mol.molecule = force_field.blocks[mol_name].to_molecule()
        return meta_mol

    @classmethod
    def from_block(cls, force_field, block, mol_name):
        """
        Constructs a :class::`MetaMolecule` from an vermouth.molecule.
        """
        # ToDo can't we get block from force-field using mol-name?
        # this function can be cleaned up a bit
        _make_edges(force_field)
        graph = MetaMolecule._block_graph_to_res_graph(block)
        meta_mol = cls(graph, force_field=force_field, mol_name=mol_name)
        meta_mol.molecule = force_field.blocks[mol_name].to_molecule()
        return meta_mol
