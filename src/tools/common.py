#  Status: being ported by Steven Watanabe
#  Base revision: 47174
#
#  Copyright (C) Vladimir Prus 2002. Permission to copy, use, modify, sell and
#  distribute this software is granted provided this copyright notice appears in
#  all copies. This software is provided "as is" without express or implied
#  warranty, and with no claim as to its suitability for any purpose.

""" Provides actions common to all toolsets, such as creating directories and
    removing files.
"""

import re
import bjam
import os
import os.path
import sys

# for some reason this fails on Python 2.7(r27:82525)
# from b2.build import virtual_target 
import b2.build.virtual_target
from b2.build import feature, type
from b2.util.utility import *
from b2.util import path, is_iterable_typed

__re__before_first_dash = re.compile ('([^-]*)-')

def reset ():
    """ Clear the module state. This is mainly for testing purposes.
        Note that this must be called _after_ resetting the module 'feature'.
    """    
    global __had_unspecified_value, __had_value, __declared_subfeature
    global __init_loc
    global __all_signatures, __debug_configuration, __show_configuration
    
    # Stores toolsets without specified initialization values.
    __had_unspecified_value = {}

    # Stores toolsets with specified initialization values.
    __had_value = {}
    
    # Stores toolsets with declared subfeatures.
    __declared_subfeature = {}
    
    # Stores all signatures of the toolsets.
    __all_signatures = {}

    # Stores the initialization locations of each toolset
    __init_loc = {}

    __debug_configuration = '--debug-configuration' in bjam.variable('ARGV')
    __show_configuration = '--show-configuration' in bjam.variable('ARGV')

    global __executable_path_variable
    OS = bjam.call("peek", [], "OS")[0]
    if OS == "NT":
        # On Windows the case and capitalization of PATH is not always predictable, so
        # let's find out what variable name was really set.
        for n in os.environ:
            if n.lower() == "path":
                __executable_path_variable = n
                break
    else:
        __executable_path_variable = "PATH"

    m = {"NT": __executable_path_variable,
         "CYGWIN": "PATH",
         "MACOSX": "DYLD_LIBRARY_PATH",
         "AIX": "LIBPATH",
         "HAIKU": "LIBRARY_PATH"}
    global __shared_library_path_variable
    __shared_library_path_variable = m.get(OS, "LD_LIBRARY_PATH")
                            
reset()

def shared_library_path_variable():
    return __shared_library_path_variable

# ported from trunk@47174
class Configurations(object):
    """
        This class helps to manage toolset configurations. Each configuration
        has a unique ID and one or more parameters. A typical example of a unique ID
        is a condition generated by 'common.check-init-parameters' rule. Other kinds
        of IDs can be used. Parameters may include any details about the configuration
        like 'command', 'path', etc.

        A toolset configuration may be in one of the following states:

        - registered
              Configuration has been registered (e.g. by autodetection code) but has
              not yet been marked as used, i.e. 'toolset.using' rule has not yet been
              called for it.
          - used
              Once called 'toolset.using' rule marks the configuration as 'used'.

        The main difference between the states above is that while a configuration is
        'registered' its options can be freely changed. This is useful in particular
        for autodetection code - all detected configurations may be safely overwritten
        by user code.
    """

    def __init__(self):
        self.used_ = set()
        self.all_ = set()
        self.params_ = {}

    def register(self, id):
        """
            Registers a configuration.

            Returns True if the configuration has been added and False if
            it already exists. Reports an error if the configuration is 'used'.
        """
        assert isinstance(id, basestring)
        if id in self.used_:
            #FIXME
            errors.error("common: the configuration '$(id)' is in use")

        if id not in self.all_:
            self.all_.add(id)

            # Indicate that a new configuration has been added.
            return True
        else:
            return False

    def use(self, id):
        """
            Mark a configuration as 'used'.

            Returns True if the state of the configuration has been changed to
            'used' and False if it the state wasn't changed. Reports an error
            if the configuration isn't known.
        """
        assert isinstance(id, basestring)
        if id not in self.all_:
            #FIXME:
            errors.error("common: the configuration '$(id)' is not known")

        if id not in self.used_:
            self.used_.add(id)

            # indicate that the configuration has been marked as 'used'
            return True
        else:
            return False

    def all(self):
        """ Return all registered configurations. """
        return self.all_

    def used(self):
        """ Return all used configurations. """
        return self.used_

    def get(self, id, param):
        """ Returns the value of a configuration parameter. """
        assert isinstance(id, basestring)
        assert isinstance(param, basestring)
        return self.params_.get(param, {}).get(id)

    def set (self, id, param, value):
        """ Sets the value of a configuration parameter. """
        assert isinstance(id, basestring)
        assert isinstance(param, basestring)
        assert is_iterable_typed(value, basestring)
        self.params_.setdefault(param, {})[id] = value

# Ported from trunk@47174
def check_init_parameters(toolset, requirement, *args):
    """ The rule for checking toolset parameters. Trailing parameters should all be
        parameter name/value pairs. The rule will check that each parameter either has
        a value in each invocation or has no value in each invocation. Also, the rule
        will check that the combination of all parameter values is unique in all
        invocations.

        Each parameter name corresponds to a subfeature. This rule will declare a
        subfeature the first time a non-empty parameter value is passed and will
        extend it with all the values.

        The return value from this rule is a condition to be used for flags settings.
    """
    assert isinstance(toolset, basestring)
    assert is_iterable_typed(requirement, basestring)
    from b2.build import toolset as b2_toolset
    if requirement is None:
        requirement = []
    sig = toolset
    condition = replace_grist(toolset, '<toolset>')
    subcondition = []

    for arg in args:
        assert(isinstance(arg, tuple))
        assert(len(arg) == 2)
        name = arg[0]
        value = arg[1]
        assert(isinstance(name, str))
        assert(isinstance(value, str) or value is None)
        
        str_toolset_name = str((toolset, name))

        # FIXME: is this the correct translation?
        ### if $(value)-is-not-empty
        if value is not None:
            condition = condition + '-' + value
            if __had_unspecified_value.has_key(str_toolset_name):
                raise BaseException("'%s' initialization: parameter '%s' inconsistent\n" \
                "no value was specified in earlier initialization\n" \
                "an explicit value is specified now" % (toolset, name))

            # The logic below is for intel compiler. It calls this rule
            # with 'intel-linux' and 'intel-win' as toolset, so we need to
            # get the base part of toolset name.
            # We can't pass 'intel' as toolset, because it that case it will
            # be impossible to register versionles intel-linux and
            # intel-win of specific version.
            t = toolset
            m = __re__before_first_dash.match(toolset)
            if m:
                t = m.group(1)

            if not __had_value.has_key(str_toolset_name):
                if not __declared_subfeature.has_key(str((t, name))):
                    feature.subfeature('toolset', t, name, [], ['propagated'])
                    __declared_subfeature[str((t, name))] = True

                __had_value[str_toolset_name] = True

            feature.extend_subfeature('toolset', t, name, [value])
            subcondition += ['<toolset-' + t + ':' + name + '>' + value ]

        else:
            if __had_value.has_key(str_toolset_name):
                raise BaseException ("'%s' initialization: parameter '%s' inconsistent\n" \
                "an explicit value was specified in an earlier initialization\n" \
                "no value is specified now" % (toolset, name))

            __had_unspecified_value[str_toolset_name] = True

        if value == None: value = ''
        
        sig = sig + value + '-'

    # if a requirement is specified, the signature should be unique
    # with that requirement
    if requirement:
        sig += '-' + '-'.join(requirement)

    if __all_signatures.has_key(sig):
        message = "duplicate initialization of '%s' with the following parameters: " % toolset
        
        for arg in args:
            name = arg[0]
            value = arg[1]
            if value == None: value = '<unspecified>'
            
            message += "'%s' = '%s'\n" % (name, value)

        raise BaseException(message)

    __all_signatures[sig] = True
    # FIXME
    __init_loc[sig] = "User location unknown" #[ errors.nearest-user-location ] ;

    # If we have a requirement, this version should only be applied under that
    # condition. To accomplish this we add a toolset requirement that imposes
    # the toolset subcondition, which encodes the version.
    if requirement:
        r = ['<toolset>' + toolset] + requirement
        r = ','.join(r)
        b2_toolset.add_requirements([r + ':' + c for c in subcondition])

    # We add the requirements, if any, to the condition to scope the toolset
    # variables and options to this specific version.
    condition = [condition]
    if requirement:
        condition += requirement

    if __show_configuration:
        print "notice:", condition
    return ['/'.join(condition)]

# Ported from trunk@47077
def get_invocation_command_nodefault(
    toolset, tool, user_provided_command=[], additional_paths=[], path_last=False):
    """
        A helper rule to get the command to invoke some tool. If
        'user-provided-command' is not given, tries to find binary named 'tool' in
        PATH and in the passed 'additional-path'. Otherwise, verifies that the first
        element of 'user-provided-command' is an existing program.
        
        This rule returns the command to be used when invoking the tool. If we can't
        find the tool, a warning is issued. If 'path-last' is specified, PATH is
        checked after 'additional-paths' when searching for 'tool'.
    """
    assert isinstance(toolset, basestring)
    assert isinstance(tool, basestring)
    assert is_iterable_typed(user_provided_command, basestring)
    assert is_iterable_typed(additional_paths, basestring) or additional_paths is None
    assert isinstance(path_last, (int, bool))

    if not user_provided_command:
        command = find_tool(tool, additional_paths, path_last) 
        if not command and __debug_configuration:
            print "warning: toolset", toolset, "initialization: can't find tool, tool"
            #FIXME
            #print "warning: initialized from" [ errors.nearest-user-location ] ;
    else:
        command = check_tool(user_provided_command)
        if not command and __debug_configuration:
            print "warning: toolset", toolset, "initialization:"
            print "warning: can't find user-provided command", user_provided_command
            #FIXME
            #ECHO "warning: initialized from" [ errors.nearest-user-location ]
            command = []
        command = ' '.join(command)

    assert(isinstance(command, str))
    
    return command

# ported from trunk@47174
def get_invocation_command(toolset, tool, user_provided_command = [],
                           additional_paths = [], path_last = False):
    """ Same as get_invocation_command_nodefault, except that if no tool is found,
        returns either the user-provided-command, if present, or the 'tool' parameter.
    """
    assert isinstance(toolset, basestring)
    assert isinstance(tool, basestring)
    assert is_iterable_typed(user_provided_command, basestring)
    assert is_iterable_typed(additional_paths, basestring) or additional_paths is None
    assert isinstance(path_last, (int, bool))

    result = get_invocation_command_nodefault(toolset, tool,
                                              user_provided_command,
                                              additional_paths,
                                              path_last)

    if not result:
        if user_provided_command:
            result = user_provided_command[0]
        else:
            result = tool

    assert(isinstance(result, str))
    
    return result

# ported from trunk@47281
def get_absolute_tool_path(command):
    """
        Given an invocation command,
        return the absolute path to the command. This works even if commnad
        has not path element and is present in PATH.
    """
    assert isinstance(command, basestring)
    if os.path.dirname(command):
        return os.path.dirname(command)
    else:
        programs = path.programs_path()
        m = path.glob(programs, [command, command + '.exe' ])
        if not len(m):
            if __debug_configuration:
                print "Could not find:", command, "in", programs
            return None
        return os.path.dirname(m[0])

# ported from trunk@47174
def find_tool(name, additional_paths = [], path_last = False):
    """ Attempts to find tool (binary) named 'name' in PATH and in
        'additional-paths'.  If found in path, returns 'name'.  If
        found in additional paths, returns full name.  If the tool
        is found in several directories, returns the first path found.
        Otherwise, returns the empty string.  If 'path_last' is specified,
        path is checked after 'additional_paths'.
    """
    assert isinstance(name, basestring)
    assert is_iterable_typed(additional_paths, basestring)
    assert isinstance(path_last, (int, bool))

    programs = path.programs_path()
    match = path.glob(programs, [name, name + '.exe'])
    additional_match = path.glob(additional_paths, [name, name + '.exe'])

    result = []
    if path_last:
        result = additional_match
        if not result and match:
            result = match

    else:
        if match:
            result = match

        elif additional_match:
            result = additional_match

    if result:
        return path.native(result[0])
    else:
        return ''

#ported from trunk@47281
def check_tool_aux(command):
    """ Checks if 'command' can be found either in path
        or is a full name to an existing file.
    """
    assert isinstance(command, basestring)
    dirname = os.path.dirname(command)
    if dirname:
        if os.path.exists(command):
            return command
        # Both NT and Cygwin will run .exe files by their unqualified names.
        elif on_windows() and os.path.exists(command + '.exe'):
            return command
        # Only NT will run .bat files by their unqualified names.
        elif os_name() == 'NT' and os.path.exists(command + '.bat'):
            return command
    else:
        paths = path.programs_path()
        if path.glob(paths, [command]):
            return command

# ported from trunk@47281
def check_tool(command):
    """ Checks that a tool can be invoked by 'command'. 
        If command is not an absolute path, checks if it can be found in 'path'.
        If comand is absolute path, check that it exists. Returns 'command'
        if ok and empty string otherwise.
    """
    assert is_iterable_typed(command, basestring)
    #FIXME: why do we check the first and last elements????
    if check_tool_aux(command[0]) or check_tool_aux(command[-1]):
        return command

# ported from trunk@47281
def handle_options(tool, condition, command, options):
    """ Handle common options for toolset, specifically sets the following
        flag variables:
        - CONFIG_COMMAND to 'command'
        - OPTIOns for compile to the value of <compileflags> in options
        - OPTIONS for compile.c to the value of <cflags> in options
        - OPTIONS for compile.c++ to the value of <cxxflags> in options
        - OPTIONS for compile.fortran to the value of <fflags> in options
        - OPTIONs for link to the value of <linkflags> in options
    """
    from b2.build import toolset

    assert isinstance(tool, basestring)
    assert is_iterable_typed(condition, basestring)
    assert command and isinstance(command, basestring)
    assert is_iterable_typed(options, basestring)
    toolset.flags(tool, 'CONFIG_COMMAND', condition, [command])
    toolset.flags(tool + '.compile', 'OPTIONS', condition, feature.get_values('<compileflags>', options))
    toolset.flags(tool + '.compile.c', 'OPTIONS', condition, feature.get_values('<cflags>', options))
    toolset.flags(tool + '.compile.c++', 'OPTIONS', condition, feature.get_values('<cxxflags>', options))
    toolset.flags(tool + '.compile.fortran', 'OPTIONS', condition, feature.get_values('<fflags>', options))
    toolset.flags(tool + '.link', 'OPTIONS', condition, feature.get_values('<linkflags>', options))

# ported from trunk@47281
def get_program_files_dir():
    """ returns the location of the "program files" directory on a windows
        platform
    """
    ProgramFiles = bjam.variable("ProgramFiles")
    if ProgramFiles:
        ProgramFiles = ' '.join(ProgramFiles)
    else:
        ProgramFiles = "c:\\Program Files"
    return ProgramFiles

# ported from trunk@47281
def rm_command():
    return __RM

# ported from trunk@47281
def copy_command():
    return __CP

# ported from trunk@47281
def variable_setting_command(variable, value):
    """
        Returns the command needed to set an environment variable on the current
        platform. The variable setting persists through all following commands and is
        visible in the environment seen by subsequently executed commands. In other
        words, on Unix systems, the variable is exported, which is consistent with the
        only possible behavior on Windows systems.
    """
    assert isinstance(variable, basestring)
    assert isinstance(value, basestring)

    if os_name() == 'NT':
        return "set " + variable + "=" + value + os.linesep
    else:
        # (todo)
        #   The following does not work on CYGWIN and needs to be fixed. On
        # CYGWIN the $(nl) variable holds a Windows new-line \r\n sequence that
        # messes up the executed export command which then reports that the
        # passed variable name is incorrect. This is most likely due to the
        # extra \r character getting interpreted as a part of the variable name.
        #
        #   Several ideas pop to mind on how to fix this:
        #     * One way would be to separate the commands using the ; shell
        #       command separator. This seems like the quickest possible
        #       solution but I do not know whether this would break code on any
        #       platforms I I have no access to.
        #     * Another would be to not use the terminating $(nl) but that would
        #       require updating all the using code so it does not simply
        #       prepend this variable to its own commands.
        #     * I guess the cleanest solution would be to update Boost Jam to
        #       allow explicitly specifying \n & \r characters in its scripts
        #       instead of always relying only on the 'current OS native newline
        #       sequence'.
        #
        #   Some code found to depend on this behaviour:
        #     * This Boost Build module.
        #         * __test__ rule.
        #         * path-variable-setting-command rule.
        #     * python.jam toolset.
        #     * xsltproc.jam toolset.
        #     * fop.jam toolset.
        #                                     (todo) (07.07.2008.) (Jurko)
        #
        # I think that this works correctly in python -- Steven Watanabe
        return variable + "=" + value + os.linesep + "export " + variable + os.linesep

def path_variable_setting_command(variable, paths):
    """
        Returns a command to sets a named shell path variable to the given NATIVE
        paths on the current platform.
    """
    assert isinstance(variable, basestring)
    assert is_iterable_typed(paths, basestring)
    sep = os.path.pathsep
    return variable_setting_command(variable, sep.join(paths))

def prepend_path_variable_command(variable, paths):
    """
        Returns a command that prepends the given paths to the named path variable on
        the current platform.
    """
    assert isinstance(variable, basestring)
    assert is_iterable_typed(paths, basestring)
    return path_variable_setting_command(variable,
        paths + os.environ.get(variable, "").split(os.pathsep))

def file_creation_command():
    """
        Return a command which can create a file. If 'r' is result of invocation, then
        'r foobar' will create foobar with unspecified content. What happens if file
        already exists is unspecified.
    """
    if os_name() == 'NT':
        return "echo. > "
    else:
        return "touch "

#FIXME: global variable
__mkdir_set = set()
__re_windows_drive = re.compile(r'^.*:\$')

def mkdir(engine, target):
    assert isinstance(target, basestring)
    # If dir exists, do not update it. Do this even for $(DOT).
    bjam.call('NOUPDATE', target)

    global __mkdir_set

    # FIXME: Where is DOT defined?
    #if $(<) != $(DOT) && ! $($(<)-mkdir):
    if target != '.' and target not in __mkdir_set:
        # Cheesy gate to prevent multiple invocations on same dir.
        __mkdir_set.add(target)

        # Schedule the mkdir build action.
        if os_name() == 'NT':
            engine.set_update_action("common.MkDir1-quick-fix-for-windows", target, [])
        else:
            engine.set_update_action("common.MkDir1-quick-fix-for-unix", target, [])

        # Prepare a Jam 'dirs' target that can be used to make the build only
        # construct all the target directories.
        engine.add_dependency('dirs', target)

        # Recursively create parent directories. $(<:P) = $(<)'s parent & we
        # recurse until root.

        s = os.path.dirname(target)
        if os_name() == 'NT':
            if(__re_windows_drive.match(s)):
                s = ''
                
        if s:
            if s != target:
                engine.add_dependency(target, s)
                mkdir(engine, s)
            else:
                bjam.call('NOTFILE', s)

__re_version = re.compile(r'^([^.]+)[.]([^.]+)[.]?([^.]*)')

def format_name(format, name, target_type, prop_set):
    """ Given a target, as given to a custom tag rule, returns a string formatted
        according to the passed format. Format is a list of properties that is
        represented in the result. For each element of format the corresponding target
        information is obtained and added to the result string. For all, but the
        literal, the format value is taken as the as string to prepend to the output
        to join the item to the rest of the result. If not given "-" is used as a
        joiner.

        The format options can be:

          <base>[joiner]
              ::  The basename of the target name.
          <toolset>[joiner]
              ::  The abbreviated toolset tag being used to build the target.
          <threading>[joiner]
              ::  Indication of a multi-threaded build.
          <runtime>[joiner]
              ::  Collective tag of the build runtime.
          <version:/version-feature | X.Y[.Z]/>[joiner]
              ::  Short version tag taken from the given "version-feature"
                  in the build properties. Or if not present, the literal
                  value as the version number.
          <property:/property-name/>[joiner]
              ::  Direct lookup of the given property-name value in the
                  build properties. /property-name/ is a regular expression.
                  e.g. <property:toolset-.*:flavor> will match every toolset.
          /otherwise/
              ::  The literal value of the format argument.

        For example this format:

          boost_ <base> <toolset> <threading> <runtime> <version:boost-version>

        Might return:

          boost_thread-vc80-mt-gd-1_33.dll, or
          boost_regex-vc80-gd-1_33.dll

        The returned name also has the target type specific prefix and suffix which
        puts it in a ready form to use as the value from a custom tag rule.
    """
    if __debug__:
        from ..build.property_set import PropertySet
        assert is_iterable_typed(format, basestring)
        assert isinstance(name, basestring)
        assert isinstance(target_type, basestring)
        assert isinstance(prop_set, PropertySet)
    # assert(isinstance(prop_set, property_set.PropertySet))
    if type.is_derived(target_type, 'LIB'):
        result = "" ;
        for f in format:
            grist = get_grist(f)
            if grist == '<base>':
                result += os.path.basename(name)
            elif grist == '<toolset>':
                result += join_tag(get_value(f), 
                    toolset_tag(name, target_type, prop_set))
            elif grist == '<threading>':
                result += join_tag(get_value(f),
                    threading_tag(name, target_type, prop_set))
            elif grist == '<runtime>':
                result += join_tag(get_value(f),
                    runtime_tag(name, target_type, prop_set))
            elif grist.startswith('<version:'):
                key = grist[len('<version:'):-1]
                version = prop_set.get('<' + key + '>')
                if not version:
                    version = key
                version = __re_version.match(version)
                result += join_tag(get_value(f), version[1] + '_' + version[2])
            elif grist.startswith('<property:'):
                key = grist[len('<property:'):-1]
                property_re = re.compile('<(' + key + ')>')
                p0 = None
                for prop in prop_set.raw():
                    match = property_re.match(prop)
                    if match:
                        p0 = match[1]
                        break
                if p0:
                    p = prop_set.get('<' + p0 + '>')
                    if p:
                        assert(len(p) == 1)
                        result += join_tag(ungrist(f), p)
            else:
                result += f

        result = b2.build.virtual_target.add_prefix_and_suffix(
            ''.join(result), target_type, prop_set)
        return result

def join_tag(joiner, tag):
    assert isinstance(joiner, basestring)
    assert isinstance(tag, basestring)
    if tag:
        if not joiner: joiner = '-'
        return joiner + tag
    return ''

__re_toolset_version = re.compile(r"<toolset.*version>(\d+)[.](\d*)")

def toolset_tag(name, target_type, prop_set):
    if __debug__:
        from ..build.property_set import PropertySet
        assert isinstance(name, basestring)
        assert isinstance(target_type, basestring)
        assert isinstance(prop_set, PropertySet)
    tag = ''

    properties = prop_set.raw()
    tools = prop_set.get('<toolset>')
    assert(len(tools) == 1)
    tools = tools[0]
    if tools.startswith('borland'): tag += 'bcb'
    elif tools.startswith('como'): tag += 'como'
    elif tools.startswith('cw'): tag += 'cw'
    elif tools.startswith('darwin'): tag += 'xgcc'
    elif tools.startswith('edg'): tag += 'edg'
    elif tools.startswith('gcc'):
        flavor = prop_set.get('<toolset-gcc:flavor>')
        ''.find
        if flavor.find('mingw') != -1:
            tag += 'mgw'
        else:
            tag += 'gcc'
    elif tools == 'intel':
        if prop_set.get('<toolset-intel:platform>') == ['win']:
            tag += 'iw'
        else:
            tag += 'il'
    elif tools.startswith('kcc'): tag += 'kcc'
    elif tools.startswith('kylix'): tag += 'bck'
    #case metrowerks* : tag += cw ;
    #case mingw* : tag += mgw ;
    elif tools.startswith('mipspro'): tag += 'mp'
    elif tools.startswith('msvc'): tag += 'vc'
    elif tools.startswith('sun'): tag += 'sw'
    elif tools.startswith('tru64cxx'): tag += 'tru'
    elif tools.startswith('vacpp'): tag += 'xlc'

    for prop in properties:
        match = __re_toolset_version.match(prop)
        if(match):
            version = match
            break
    version_string = None
    # For historical reasons, vc6.0 and vc7.0 use different naming.
    if tag == 'vc':
        if version.group(1) == '6':
            # Cancel minor version.
            version_string = '6'
        elif version.group(1) == '7' and version.group(2) == '0':
            version_string = '7'

    # On intel, version is not added, because it does not matter and it's the
    # version of vc used as backend that matters. Ideally, we'd encode the
    # backend version but that would break compatibility with V1.
    elif tag == 'iw':
        version_string = ''

    # On borland, version is not added for compatibility with V1.
    elif tag == 'bcb':
        version_string = ''

    if version_string is None:
        version = version.group(1) + version.group(2)

    tag += version

    return tag


def threading_tag(name, target_type, prop_set):
    if __debug__:
        from ..build.property_set import PropertySet
        assert isinstance(name, basestring)
        assert isinstance(target_type, basestring)
        assert isinstance(prop_set, PropertySet)
    tag = ''
    properties = prop_set.raw()
    if '<threading>multi' in properties: tag = 'mt'

    return tag


def runtime_tag(name, target_type, prop_set ):
    if __debug__:
        from ..build.property_set import PropertySet
        assert isinstance(name, basestring)
        assert isinstance(target_type, basestring)
        assert isinstance(prop_set, PropertySet)
    tag = ''

    properties = prop_set.raw()
    if '<runtime-link>static' in properties: tag += 's'

    # This is an ugly thing. In V1, there's a code to automatically detect which
    # properties affect a target. So, if <runtime-debugging> does not affect gcc
    # toolset, the tag rules won't even see <runtime-debugging>. Similar
    # functionality in V2 is not implemented yet, so we just check for toolsets
    # which are known to care about runtime debug.
    if '<toolset>msvc' in properties \
       or '<stdlib>stlport' in properties \
       or '<toolset-intel:platform>win' in properties:
        if '<runtime-debugging>on' in properties: tag += 'g'

    if '<python-debugging>on' in properties: tag += 'y'
    if '<variant>debug' in properties: tag += 'd'
    if '<stdlib>stlport' in properties: tag += 'p'
    if '<stdlib-stlport:iostream>hostios' in properties: tag += 'n'

    return tag


## TODO:
##rule __test__ ( )
##{
##    import assert ;
##
##    local nl = "
##" ;
##
##    local save-os = [ modules.peek os : .name ] ;
##
##    modules.poke os : .name : LINUX ;
##
##    assert.result "PATH=foo:bar:baz$(nl)export PATH$(nl)"
##        : path-variable-setting-command PATH : foo bar baz ;
##
##    assert.result "PATH=foo:bar:$PATH$(nl)export PATH$(nl)"
##        : prepend-path-variable-command PATH : foo bar ;
##
##    modules.poke os : .name : NT ;
##
##    assert.result "set PATH=foo;bar;baz$(nl)"
##        : path-variable-setting-command PATH : foo bar baz ;
##
##    assert.result "set PATH=foo;bar;%PATH%$(nl)"
##        : prepend-path-variable-command PATH : foo bar ;
##
##    modules.poke os : .name : $(save-os) ;
##}

def init(manager):
    engine = manager.engine()

    engine.register_action("common.MkDir1-quick-fix-for-unix", 'mkdir -p "$(<)"')
    engine.register_action("common.MkDir1-quick-fix-for-windows", 'if not exist "$(<)\\" mkdir "$(<)"')

    import b2.tools.make
    import b2.build.alias

    global __RM, __CP, __IGNORE, __LN
    # ported from trunk@47281
    if os_name() == 'NT':
        __RM = 'del /f /q'
        __CP = 'copy'
        __IGNORE = '2>nul >nul & setlocal'
        __LN = __CP
        #if not __LN:
        #    __LN = CP
    else:
        __RM = 'rm -f'
        __CP = 'cp'
        __IGNORE = ''
        __LN = 'ln'
        
    engine.register_action("common.Clean", __RM + ' "$(>)"',
                           flags=['piecemeal', 'together', 'existing'])
    engine.register_action("common.copy", __CP + ' "$(>)" "$(<)"')
    engine.register_action("common.RmTemps", __RM + ' "$(>)" ' + __IGNORE,
                           flags=['quietly', 'updated', 'piecemeal', 'together'])

    engine.register_action("common.hard-link", 
        __RM + ' "$(<)" 2$(NULL_OUT) $(NULL_OUT)' + os.linesep +
        __LN + ' "$(>)" "$(<)" $(NULL_OUT)')
