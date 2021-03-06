############################################################
#                                                          #
#                          hprose                          #
#                                                          #
# Official WebSite: http://www.hprose.com/                 #
#                   http://www.hprose.net/                 #
#                   http://www.hprose.org/                 #
#                                                          #
############################################################

############################################################
#                                                          #
# hprose/server.py                                         #
#                                                          #
# hprose server for python 3.0+                            #
#                                                          #
# LastModified: Jun 22, 2011                               #
# Author: Ma Bingyao <andot@hprfc.com>                     #
#                                                          #
############################################################

import types
from sys import modules
from hprose.io import *

def _getInstanceMethods(cls):
    v = vars(cls)
    return [name for name in v if isinstance(v[name], types.FunctionType)]

def _getClassMethods(cls):
    v = vars(cls)
    return [name for name in v if isinstance(v[name], classmethod)]

def _getStaticMethods(cls):
    v = vars(cls)
    return [name for name in v if isinstance(v[name], staticmethod)]

class HproseService(object):
    def __init__(self):
        self.__functions = {}
        self.__funcNames = {}
        self.__resultMode = {}
        self._debug = False
        self.onBeforeInvoke = None
        self.onAfterInvoke = None
        self.onSendHeader = None
        self.onSendError = None

    def _doInvoke(self, reader, writer, session, environ):
        tag = HproseTags.TagCall;
        while tag == HproseTags.TagCall:
            reader.reset()
            functionName = reader.readString()
            aliasName = functionName.lower()
            functionArgs = []
            byref = False
            has_session_args = False
            result = None
            tag = reader.checkTags((HproseTags.TagList,
                                    HproseTags.TagEnd,
                                    HproseTags.TagCall))
            if tag == HproseTags.TagList:
                reader.reset()
                functionArgs = reader.readList(False)
                tag = reader.checkTags((HproseTags.TagTrue,
                                        HproseTags.TagEnd,
                                        HproseTags.TagCall))
                if (tag == HproseTags.TagTrue):
                    byref = True
                    tag = reader.checkTags((HproseTags.TagEnd,
                                            HproseTags.TagCall))
            if self.onBeforeInvoke != None:
                if hasattr(self.onBeforeInvoke, 'func_code'):
                    argcount = self.onBeforeInvoke.func_code.co_argcount
                    if argcount == 5:
                        self.onBeforeInvoke(session, environ, functionName, functionArgs, byref)
                    elif argcount == 4:
                        self.onBeforeInvoke(environ, functionName, functionArgs, byref)                    
                    elif argcount == 3:
                        self.onBeforeInvoke(functionName, functionArgs, byref)
                    elif argcount == 2:
                        self.onBeforeInvoke(functionName, functionArgs)
                    elif argcount == 1:
                        self.onBeforeInvoke(functionName)
                    elif argcount == 0:
                        self.onBeforeInvoke()
                else:
                    self.onBeforeInvoke(environ, functionName, functionArgs, byref)              
            if aliasName in self.__functions:
                function = self.__functions[aliasName]
                resultMode = self.__resultMode[aliasName]
                if hasattr(function, '__code__'):
                    fc = function.__code__
                    has_session_args = ((fc.co_argcount > 0) and
                        (fc.co_varnames[fc.co_argcount - 1] == 'session'))
                    if has_session_args:
                        n = len(functionArgs) - fc.co_argcount + len(function.func_defaults)
                        functionArgs.extend(function.func_defaults[n:-1])
                        functionArgs.insert(fc.co_argcount - 1, session)
                result = function(*functionArgs)
            elif '*' in self.__functions:
                function = self.__functions['*']
                resultMode = self.__resultMode['*']
                if hasattr(function, 'func_code'):
                    argcount = function.func_code.co_argcount
                    if argcount == 4:
                        result = function(session, environ, functionName, functionArgs)
                    elif argcount == 3:
                        result = function(environ, functionName, functionArgs)
                    elif argcount == 2:
                        result = function(functionName, functionArgs)
                    elif argcount == 1:
                        result = function(functionName)
                    elif argcount == 0:
                        result = function()
                else:
                    result = function(functionName, functionArgs)
            else:
                raise HproseException("Can't find this function %s()." % functionName)
            if self.onAfterInvoke != None:
                if hasattr(self.onAfterInvoke, 'func_code'):
                    argcount = self.onAfterInvoke.func_code.co_argcount
                    if argcount == 6:
                        self.onAfterInvoke(session, environ, functionName, functionArgs, byref, result)
                    elif argcount == 5:
                        self.onAfterInvoke(environ, functionName, functionArgs, byref, result)
                    elif argcount == 4:
                        self.onAfterInvoke(functionName, functionArgs, byref, result)                    
                    elif argcount == 3:
                        self.onAfterInvoke(functionName, functionArgs, byref)
                    elif argcount == 2:
                        self.onAfterInvoke(functionName, functionArgs)
                    elif argcount == 1:
                        self.onAfterInvoke(functionName)
                    elif argcount == 0:
                        self.onAfterInvoke()
                else:
                    self.onAfterInvoke(environ, functionName, functionArgs, byref, result)       
            if resultMode == HproseResultMode.RawWithEndTag:
                writer.stream.write(result)
                return
            if resultMode == HproseResultMode.Raw:
                writer.stream.write(result)            
            else:
                writer.stream.write(HproseTags.TagResult)
                if resultMode == HproseResultMode.Serialized:
                    writer.stream.write(result)
                else:
                    writer.reset()
                    writer.serialize(result)
                if byref:
                    if has_session_args:
                        del functionArgs[fc.co_argcount - 1]
                    writer.stream.write(HproseTags.TagArgument)
                    writer.reset()
                    writer.writeList(functionArgs, False)
        writer.stream.write(HproseTags.TagEnd)

    def _doFunctionList(self, writer):
        writer.stream.write(HproseTags.TagFunctions)
        writer.writeList(list(self.__funcNames.values()), False)
        writer.stream.write(HproseTags.TagEnd)

    def addMissingFunction(self, function, resultMode = HproseResultMode.Normal):
        self.addFunction(function, '*', resultMode)

    def addFunction(self, function, alias = None, resultMode = HproseResultMode.Normal):
        if isinstance(function, str):
            function = getattr(modules['__main__'], function, None)
        if not hasattr(function, '__call__'):
            raise HproseException('Argument function is not callable')
        if alias == None:
            alias = function.__name__
        if isinstance(alias, str):
            aliasName = alias.lower()
            self.__functions[aliasName] = function
            self.__funcNames[aliasName] = alias
            self.__resultMode[aliasName] = resultMode
        else:
            raise HproseException('Argument alias is not a string')

    def addFunctions(self, functions, aliases = None, resultMode = HproseResultMode.Normal):
        aliases_is_null = (aliases == None)
        if not isinstance(functions, (list, tuple)):
            raise HproseException('Argument functions is not a list or tuple')
        count = len(functions)
        if not aliases_is_null and count != len(aliases):
            raise HproseException('The count of functions is not matched with aliases')
        for i in range(count):
            function = functions[i]
            if aliases_is_null:
                self.addFunction(function, None, resultMode)
            else:
                self.addFunction(function, aliases[i], resultMode)

    def addMethod(self, methodname, belongto, alias = None, resultMode = HproseResultMode.Normal):
        function = getattr(belongto, methodname, None)
        if alias == None:
            self.addFunction(function, methodname, resultMode)
        else:
            self.addFunction(function, alias, resultMode)

    def addMethods(self, methods, belongto, aliases = None, resultMode = HproseResultMode.Normal):
        aliases_is_null = (aliases == None)
        if not isinstance(methods, (list, tuple)):
            raise HproseException('Argument methods is not a list or tuple')
        if isinstance(aliases, str):
            aliasPrefix = aliases
            aliases = [aliasPrefix + '_' + name for name in methods]
        count = len(methods)
        if not aliases_is_null and count != len(aliases):
            raise HproseException('The count of methods is not matched with aliases')
        for i in range(count):
            method = methods[i]
            function = getattr(belongto, method, None)
            if aliases_is_null:
                self.addFunction(function, method, resultMode)
            else:
                self.addFunction(function, aliases[i], resultMode)

    def addInstanceMethods(self, obj, cls = None, aliasPrefix = None, resultMode = HproseResultMode.Normal):
        if cls == None: cls = obj.__class__
        self.addMethods(_getInstanceMethods(cls), obj, aliasPrefix, resultMode)


    def addClassMethods(self, cls, execcls = None, aliasPrefix = None, resultMode = HproseResultMode.Normal):
        if execcls == None: execcls = cls
        self.addMethods(_getClassMethods(cls), execcls, aliasPrefix, resultMode)

    def addStaticMethods(self, cls, aliasPrefix = None, resultMode = HproseResultMode.Normal):
        self.addMethods(_getStaticMethods(cls), cls, aliasPrefix, resultMode)

    def add(self, *args):
        args_num = len(args)
        if args_num == 1:
            if isinstance(args[0], (tuple, list)):
                self.addFunctions(args[0])
            elif isinstance(args[0], type):
                self.addClassMethods(args[0])
                self.addStaticMethods(args[0])
            elif hasattr(args[0], '__call__'):
                self.addFunction(args[0])
            else:
                self.addInstanceMethods(args[0])
        elif args_num == 2:
            if isinstance(args[0], type):
                if isinstance(args[1], type):
                    self.addClassMethods(args[0], args[1])
                else:
                    self.addClassMethods(args[0], args[0], args[1])
                    self.addStaticMethods(args[0], args[1])
            elif isinstance(args[0], str):
                if isinstance(args[1], str):
                    self.addFunction(args[0], args[1])
                else:
                    self.addMethod(args[0], args[1])
            elif isinstance(args[0], (tuple, list)):
                if isinstance(args[1], (tuple, list)):
                    self.addFunctions(args[0], args[1])
                else:
                    self.addMethods(args[0], args[1])
            elif hasattr(args[0], '__call__') and isinstance(args[1], str):
                self.addFunction(args[0], args[1])
            elif isinstance(args[1], str):
                self.addInstanceMethods(args[0], None, args[1])
            else:
                self.addInstanceMethods(args[0], args[1])
        elif args_num == 3:
            if isinstance(args[0], str) and isinstance(args[2], str):
                if args[1] == None:
                    self.addFunction(args[0], args[2])
                else:
                    self.addMethod(args[0], args[1], args[2])
            elif isinstance(args[0], (tuple, list)):
                if isinstance(args[2], (tuple, list)) and args[1] == None:
                    self.addFunctions(args[0], args[2])
                else:
                    self.addMethods(args[0], args[1], args[2])
            elif isinstance(args[1], type) and isinstance(args[2], str):
                if isinstance(args[0], type):
                    self.addClassMethods(args[0], args[1], args[2])
                else:
                    self.addInstanceMethods(args[0], args[1], args[2])
            elif hasattr(args[0], '__call__') and args[1] == None and isinstance(args[2], str):
                self.addFunction(args[0], args[2])
            else:
                raise HproseException('Wrong arguments')
        else:
            raise HproseException('Wrong arguments')

    def isDebugEnabled(self):
        return self._debug
        
    def setDebugEnabled(self, enable = True):
        self._debug = enable
