#!/bin/sh
# Compile-checks the plugin against small stand-ins for the VaM API, checks that it only references .NET namespaces
# VaM allows, and runs the logic tests. Needs Mono (the "mcs" compiler and "mono"). Run from this folder.
set -e
mcs -target:library -out:Stubs.dll Stubs.cs
mcs -target:library -r:Stubs.dll -out:Senses.dll ../VaMRT/VaMRT_Senses.cs

# VaM refuses to compile plugins that reference certain namespaces. The reference can be indirect:
# for example e.GetType().Name silently references System.Reflection. Fail here instead of inside VaM.
if strings -a Senses.dll | grep -E "^System\.(Reflection|IO|Net|Diagnostics\.Process|Threading)(\.|$)" ; then
    echo "FAIL: the plugin references a namespace VaM prohibits (see above)."; exit 1
fi
echo "namespace check ok"

# VaM treats the FIRST class in the file as the plugin ("must inherit from MVRScript" otherwise).
if command -v monodis >/dev/null 2>&1; then
    first=$(monodis --typedef Senses.dll 2>/dev/null | sed -n '3p' | awk '{print $2}')
    if [ "$first" != "VaMRT.Senses" ]; then
        echo "FAIL: the first class in the file is '$first'; the MVRScript plugin class VaMRT.Senses must come first."; exit 1
    fi
    echo "class order check ok"
else
    echo "note: monodis not found, skipped the class-order check (install mono-utils)"
fi

mcs -r:Stubs.dll -r:Senses.dll -out:Test.exe Test.cs
mono Test.exe
