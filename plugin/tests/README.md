These tests run OUTSIDE VaM. `Stubs.cs` imitates only the VaM/Unity calls the plugin uses (signatures taken from
plugins that run in VaM), so a clean compile here proves the syntax and types, not that VaM behaves the same.
`Test.cs` checks the pure logic (`SensesLogic`): directions, pose classification, tagging, and the generated text.
Add a test whenever you change that logic.

## Rule for the stubs
`Stubs.cs` may only contain VaM calls that were seen in a plugin that runs in VaM, with the source noted in a comment. Version 0.3.0 broke because a
stub invented a class (`EventTrigger`) that is not part of VaM. A clean compile here only means the code is consistent with the stubs.
