import os
from vermouth.parser_utils import SectionLineParser
from vermouth.molecule import Interaction
from vermouth.gmx.itp_read import read_itp
from .meta_molecule import MetaMolecule

class TOPDirector(SectionLineParser):

    COMMENT_CHAR = ';'

    atom_idxs = {'bonds': [0, 1],
                 'bondtypes':[0, 1],
                 'position_restraints': [0],
                 'angles': [0, 1, 2],
                 'angletypes':[0, 1, 2],
                 'constraints': [0, 1],
                 'dihedrals': [0, 1, 2, 3],
                 'dihedraltypes': [0, 1, 2, 3],
                 'pairs': [0, 1],
                 'pairtypes': [0, 1],
                 'exclusions': [slice(None, None)],
                 'virtual_sitesn': [0, slice(2, None)],
                 'virtual_sites2': [0, 1, 2, 3],
                 'virtual_sites3': [0, 1, 2, 3],
                 'pairs_nb': [0, 1],
                 'SETTLE': [0],
                 'virtual_sites4': [slice(0, 5)],
                 'distance_restraints':  [0, 1],
                 'dihedral_restraints':  [slice(0, 4)],
                 'orientation_restraints': [0, 1],
                 'angle_restraints': [slice(0, 4)],
                 'angle_restraints_z': [0, 1]}

    def __init__(self, topology, cwdir=None):
        super().__init__()
        self.force_field = topology.force_field
        self.topology = topology
        self.current_meta = None
        self.current_itp = None
        self.itp_lines = []
        self.molecules = []
        self.cwdir = cwdir
        self.header_actions = {
            ('moleculetype',): self._new_itp
        }
        self.pragma_actions = {
            '#define': self.parse_define,
            '#include': self.parse_include
        }

    def dispatch(self, line):
        """
        Looks at `line` to see what kind of line it is, and returns either
        :meth:`parse_header` if `line` is a section header or
        :meth:`vermouth.parser_utils.SectionLineParser.parse_section` otherwise.
        Calls :meth:`vermouth.parser_utils.SectionLineParser.is_section_header` to see
        whether `line` is a section header or not.

        Parameters
        ----------
        line: str

        Returns
        -------
        collections.abc.Callable
            The method that should be used to parse `line`.
        """

        if self.is_section_header(line):
            return self.parse_header
        elif self.is_pragma(line):
            return self.parse_top_pragma
        else:
            return self.parse_section

    @staticmethod
    def is_pragma(line):
        """
        Parameters
        ----------
        line: str
            A line of text.

        Returns
        -------
        bool
            ``True`` if `line` is a def statement.
        """
        return line.startswith('#')

    def parse_top_pragma(self, line, lineno=0):
        """
        Parses the beginning and end of define sections
        with line number `lineno`. Sets attr current_meta
        when applicable. Does check if ifdefs overlap.

        Parameters
        ----------
        line: str
        lineno: str

        Returns
        -------
        object
            The result of calling :meth:`finalize_section`, which is called
            if a section ends.

        Raises
        ------
        IOError
            If the def sections are missformatted
        """
        if line == '#endif':
            if self.current_itp:
                self.current_itp.append(line)
            elif self.current_meta is None:
                raise IOError("Your #ifdef section is orderd incorrectly."
                              "At line {} I read #endif but I haven not read"
                              "a ifdef before.".format(lineno))

        elif line.startswith("#ifdef") or line.startswith("#ifndef"):
            if self.current_itp:
                self.current_itp.append(line)
            elif self.current_meta is None:
                condition, tag = line.split()
                self.current_meta = {'tag': tag,
                                     'condition': condition.replace("#", "")}
            elif self.current_meta is not None:
                raise IOError("Your #ifdef/#ifndef section is orderd incorrectly."
                              "At line {} I read {} but there is still"
                              "an open #ifdef/#ifndef section from"
                              "before.".format(lineno, line.split()[0]))

        elif line.split()[0] in self.pragma_actions:
            action = self.pragma_actions[line.split()[0]]
            action(line)
        else:
            raise IOError("Don't know how to parse pargma {} at"
                          "line {}.".format(line, lineno))

    def parse_header(self, line, lineno=0):
        """
        Parses a section header with line number `lineno`. Sets
        :attr:`vermouth.parser_utils.SectionLineParser.section`
        when applicable. Does not check whether `line` is a valid section
        header.

        Parameters
        ----------
        line: str
        lineno: str

        Returns
        -------
        object
            The result of calling :meth:`finalize_section`, which is called
            if a section ends.

        Raises
        ------
        KeyError
            If the section header is unknown.
        """
        prev_section = self.section

        ended = []
        section = self.section + [line.strip('[ ]').casefold()]
        if tuple(section[-1:]) in self.METH_DICT:
            self.section = section[-1:]
        else:
            while tuple(section) not in self.METH_DICT and len(section) > 1:
                ended.append(section.pop(-2))  # [a, b, c, d] -> [a, b, d]
            self.section = section

        result = None

        if len(prev_section) != 0:
            result = self.finalize_section(prev_section, ended)

        action = self.header_actions.get(tuple(self.section))
        if action:
            action()

        if not isinstance(self.current_itp, type(None)):
           self.current_itp.append(line)

        return result

    def finalize(self, lineno=0):
        """
        Called at the end of the file and checks that all pragmas are closed
        before calling the parent method.
        """
        if self.current_itp:
           self.itp_lines.append(self.current_itp)

        if self.current_meta is not None:
            raise IOError("Your #ifdef/#ifndef section is orderd incorrectly."
                          "There is no #endif for the last pragma.")

        for lines in self.itp_lines:
            read_itp(lines, self.force_field)

        for mol_name, n_mol in self.molecules:
            block = self.force_field.blocks[mol_name]
            meta_molecule = MetaMolecule.from_block(self.force_field,
                                                    block,
                                                    mol_name)
            meta_molecule.atom_types = self.topology.atom_types
            meta_molecule.defaults = self.topology.defaults
            meta_molecule.nonbond_params = self.topology.nonbond_params
            for idx in range(0, int(n_mol)):
                 self.topology.add_molecule(meta_molecule)

        super().finalize()

    def _new_itp(self):
        if self.current_itp:
           self.itp_lines.append(self.current_itp)
        self.current_itp = []

    @SectionLineParser.section_parser('system')
    def _system(self, line, lineno=0):
        """
        Parses the lines in the '[system]'
        directive and stores it.
        """
        system_lines = self.topology.discription
        system_lines.append(line)
        self.discription = system_lines

    @SectionLineParser.section_parser('molecules')
    def _molecules(self, line, lineno=0):
        """
        Parses the lines in the '[molecules]'
        directive and stores it.
        """
        # we need to keep the order here so cannot make it a dict
        # also mol names do not need to be unique
        name, n_mol = line.split()
        self.molecules.append((name, n_mol))

    @SectionLineParser.section_parser('defaults')
    def _defaults(self, line, lineno=0):
        """
        Parse and store the defaults section.
        """
        defaults = ["nbfunc", "comb-rule", "gen-pairs", "fudgeLJ", "fudgeQQ"]
        numbered_terms = ["nbfunc", "comb-rule", "fudgeLJ", "fudgeQQ"]
        tokens = line.split()

        self.topology.defaults = dict(zip(defaults[0:len(tokens)], tokens))
        for token_name in numbered_terms:
            if token_name in self.topology.defaults:
                 self.topology.defaults[token_name] = float(self.topology.defaults[token_name])

    @SectionLineParser.section_parser('atomtypes')
    def _atomtypes(self, line, lineno=0):
        """
        Parse and store atomtypes section
        """
        atom_name = line.split()[0]
        nb1, nb2 = line.split()[-2:]
        self.topology.atom_types[atom_name] = {"nb1": float(nb1),
                                              "nb2": float(nb2)}

    @SectionLineParser.section_parser('nonbond_params')
    def _nonbond_params(self, line, lineno=0):
        """angletypes
        Parse and store nonbond params
        """
        atom_1, atom_2, func, nb1, nb2 = line.split()
        self.topology.nonbond_params[(atom_1, atom_2)] = {"f": int(func),
                                                          "nb1": float(nb1),
                                                          "nb2": float(nb2)}
    @SectionLineParser.section_parser('pairtypes')
    @SectionLineParser.section_parser('angletypes')
    @SectionLineParser.section_parser('dihedraltypes')
    @SectionLineParser.section_parser('bondtypes')
    def _type_params(self, line, lineno=0):
        """
        Parse and store bonded types
        """
        section_name = self.section[-1]
        atoms, params = self._split_atoms_and_parameters(line.split(),
                                                         self.atom_idxs[section_name])
        new_interaction = Interaction(atoms=atoms,
                                      parameters=params,
                                      meta=self.current_meta)
        self.topology.types[section_name].append(new_interaction)

    @SectionLineParser.section_parser('moleculetype')
    @SectionLineParser.section_parser('moleculetype', 'atoms')
    @SectionLineParser.section_parser('moleculetype', 'bonds')
    @SectionLineParser.section_parser('moleculetype', 'angles')
    @SectionLineParser.section_parser('moleculetype', 'dihedrals')
    @SectionLineParser.section_parser('moleculetype', 'impropers')
    @SectionLineParser.section_parser('moleculetype', 'constraints')
    @SectionLineParser.section_parser('moleculetype', 'pairs')
    @SectionLineParser.section_parser('moleculetype', 'exclusions')
    @SectionLineParser.section_parser('moleculetype', 'virtual_sites2')
    @SectionLineParser.section_parser('moleculetype', 'virtual_sites3')
    @SectionLineParser.section_parser('moleculetype', 'virtual_sites4')
    @SectionLineParser.section_parser('moleculetype', 'virtual_sitesn')
    @SectionLineParser.section_parser('moleculetype', 'position_restraints')
    @SectionLineParser.section_parser('moleculetype', 'pairs_nb')
    @SectionLineParser.section_parser('moleculetype', 'SETTLE')
    @SectionLineParser.section_parser('moleculetype', 'distance_restraints')
    @SectionLineParser.section_parser('moleculetype', 'orientation_restraints')
    @SectionLineParser.section_parser('moleculetype', 'angle_restraints')
    @SectionLineParser.section_parser('moleculetype', 'angle_restraints_z')
    def _molecule(self, line, lineno=0):
        """
        Parses the lines of the [atoms] directive.
        """
        self.current_itp.append(line)

    def parse_define(self, line):
        """
        Parse define statemetns
        """
        tokens = line.split()

        if len(tokens) > 2:
            tag = line.split()[1]
            parameters = line.split()[2:]
        else:
            _, tag = line.split()
            parameters = True

        definition = {tag: parameters}
        self.topology.defines.update(definition)

    def parse_include(self, line):
        """
        parse include statemnts
        """
        path = line.split()[1].strip('\"')
        print(self.cwdir)
        if self.cwdir:
           filename = os.path.join(self.cwdir, path)
           cwdir = os.path.dirname(filename)
        else:
           cwdir = os.path.dirname(path)
           filename = path

        with open(filename, 'r') as _file:
            lines = _file.readlines()

        read_topology(lines, topology=self.topology, cwdir=cwdir)

    def _split_atoms_and_parameters(self, tokens, atom_idxs):
        """
        Returns atoms from line based on the indices defined in `atom_idxs`.
        It also interprets slices etc. stored as strings.

        Parameters:
        ------------
        tokens: collections.deque[str]
            Deque of token to inspect. The deque **can be modified** in place.
        atom_idxs: list of ints or strings that are valid python slices

        Returns:
        -----------
        list
        """

        atoms = []
        remove = []
        # first we extract the atoms from the indices given using
        # ints or slices
        for idx in atom_idxs:
            if isinstance(idx, int):
                atoms.append(tokens[idx])
                remove.append(idx)
            elif isinstance(idx, slice):
                atoms += [atom for atom in tokens[idx]]
                idx_range = range(0, len(tokens))
                remove += idx_range[idx]
            else:
                raise IOError

        # everything that is left are parameters, which we
        # get by simply deleting the atoms from tokens

        for index in sorted(remove, reverse=True):
            del tokens[index]

        return atoms, tokens


def read_topology(lines, topology, cwdir=None):
    """
    Parses `lines` of itp format and adds the
    molecule as a block to `force_field`.

    Parameters
    ----------
    lines: list
        list of lines of an itp file
    force_field: :class:`vermouth.forcefield.ForceField`
    """
    director = TOPDirector(topology, cwdir)
    return list(director.parse(iter(lines)))
