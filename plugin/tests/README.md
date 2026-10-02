These tests run OUTSIDE VaM. `Stubs.cs` imitates only the VaM/Unity calls the plugin uses (signatures taken from
plugins that run in VaM), so a clean compile here proves the syntax and types, not that VaM behaves the same.
`Test.cs` checks the pure logic (`SensesLogic`): directions, pose classification, tagging, and the generated text.
Add a test whenever you change that logic.
