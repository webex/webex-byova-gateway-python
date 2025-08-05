# Connectors

This directory contains vendor connector implementations for the Webex Contact Center BYOVA Gateway.

## Purpose

Connectors handle communication with different vendor systems and platforms, providing a unified interface for the core gateway.

## Structure

- Each vendor connector should be implemented as a separate module
- Connectors should implement a common interface for consistency
- Local connector implementations can include audio file handling

## Example Connectors

- Local connector (for testing with audio files)
- Webex Contact Center connector
- Third-party vendor connectors 