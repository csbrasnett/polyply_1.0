import networkx as nx
from polyply.src.processor import Processor

class MapToMolecule(Processor):
    """
    This processor takes a :class:`MetaMolecule` and generates a
    :class:`vermouth.molecule.Molecule`, which consists at this stage
    of disconnected blocks. These blocks can be connected using the
    :class:`ConnectMolecule` processor. It can either run on a
    single meta molecule or a system. The later is currently not
    implemented.
    """
    @staticmethod
    def expand_meta_graph(meta_molecule, block, meta_mol_node):
        """
        When a multiresidue block is encounterd the individual
        residues are added instead of the orignial block to
        the meta molecule.
        """
        # 1. relable nodes to make space for new nodes to be inserted
        mapping = {}
        offset = len(set(nx.get_node_attributes(block, "resid").values())) - 1
        print("offset", offset)
        for node in meta_molecule.nodes:
            if node > meta_mol_node:
                mapping[node] = node + offset

        nx.relabel_nodes(meta_molecule, mapping, copy=False)

        # 2. add the new nodes to the meta molecule overwriting
        # the inital node
        node_to_resid = {}
        resids = nx.get_node_attributes(block, "resid")
        for node, resid in resids.items():
            if resid != meta_mol_node:
               node_to_resid[node] = resid + meta_mol_node - 1
            else:
               node_to_resid[node] = resid

        #print(node_to_resid)
        meta_molecule.add_nodes_from(set(node_to_resid.values()))

        # 3. set node attributes
        name_dict = {}
        ignore_dict = {}
        resnames = nx.get_node_attributes(block, "resname")
        for idx, value in resnames.items():
            name_dict.update({node_to_resid[idx]:value})
            ignore_dict.update({node_to_resid[idx]:False})

        nx.set_node_attributes(meta_molecule, name_dict, "resname")
        nx.set_node_attributes(meta_molecule, ignore_dict, "links")

        # 4. add all missing edges
        block.make_edges_from_interaction_type(type_="bonds")
        #print(block.edges)
        for edge in block.edges:
            v1 = node_to_resid[edge[0]]
            v2 = node_to_resid[edge[1]]
            if v1 != v2:
               meta_molecule.add_edge(v1, v2)

    @staticmethod
    def add_blocks(meta_molecule):
        """
        Add disconnected blocks to :class:`vermouth.molecule.Molecue`
        and if a multiresidue block is encountered expand the meta
        molecule graph to include the block at residue level.
        """
        force_field = meta_molecule.force_field
        block = force_field.blocks[meta_molecule.nodes[0]["resname"]]
        new_mol = block.to_molecule()

        if len(set(nx.get_node_attributes(block, "resname").values())) > 1:
            MapToMolecule.expand_meta_graph(meta_molecule, block, 0)

        for node in list(meta_molecule.nodes.keys())[1:]:
            resname = meta_molecule.nodes[node]["resname"]

            if node + 1 in nx.get_node_attributes(new_mol, "resid").values():
               continue

            block = force_field.blocks[resname]
            new_mol.merge_molecule(block)
            if len(set(nx.get_node_attributes(block, "resname").values())) > 1:
                MapToMolecule.expand_meta_graph(meta_molecule, block, node)

        return new_mol

    def run_molecule(self, meta_molecule):
        """
        Process a single molecule. Must be implemented by subclasses.
        Parameters
        ----------
        molecule: polyply.src.meta_molecule.MetaMolecule
             The meta molecule to process.
        Returns
        -------
        vermouth.molecule.Molecule
            Either the provided molecule, or a brand new one.
        """
        new_molecule = self.add_blocks(meta_molecule)
        meta_molecule.molecule = new_molecule
        return meta_molecule
