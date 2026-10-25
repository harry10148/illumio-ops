"""The flow database (data/flows.sqlite): everything collected from one PCE.

Kept apart from the application state database so that switching to another PCE
replaces this whole file and touches nothing else.
"""
