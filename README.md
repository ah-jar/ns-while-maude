# Semántica natural operacional de WHILE en Maude

Implementación ejecutable en **Maude** de la semántica natural operacional (*big-step semantics*) de un lenguaje imperativo WHILE simplificado.

El proyecto permite definir programas, ejecutarlos sobre un estado inicial y obtener directamente su estado final. Su propósito es conectar la especificación matemática de un lenguaje con una implementación formal que puede ejecutarse y comprobarse.

## Fundamento teórico

La implementación se basa principalmente en el lenguaje WHILE y en las reglas de semántica natural presentadas por **Hanne Riis Nielson y Flemming Nielson** en *Semantics with Applications: A Formal Introduction*.

Una transición tiene la forma:

```text
⟨S, s⟩ → s′
```

donde `S` es una sentencia, `s` el estado inicial y `s′` el estado final. En Maude, esta relación se representa mediante configuraciones y reglas de reescritura:

```maude
op <_,_> : Stat State -> Config .
```

Las siguientes figuras muestran la correspondencia entre las reglas formales y su implementación:

![Equivalencia de las reglas de asignación, skip y composición](docs/semantics-basic.svg)

![Equivalencia de las reglas condicionales y de bucle](docs/semantics-control.svg)

## Construcciones implementadas

| Categoría | Construcciones |
|---|---|
| Expresiones aritméticas | enteros, variables, suma, resta y multiplicación |
| Condiciones booleanas | constantes, igualdad, menor o igual, negación y conjunción |
| Sentencias | asignación, `skip`, composición, condicional y bucle `while` |
| Estado | consulta y actualización de variables |

## Estructura

```text
.
├── state.maude
├── arithmetic_syntax.maude
├── arithmetic_semantics.maude
├── bool_syntax.maude
├── bool_semantics.maude
├── ns_while_syntax.maude
└── ns_while_semantics.maude
```

Los módulos de sintaxis definen el lenguaje, mientras que los módulos de semántica implementan la evaluación de expresiones y las reglas de ejecución.

## Ejecución

Con Maude instalado, inicie el intérprete desde el directorio del proyecto:

```bash
maude
```

Cargue los módulos respetando sus dependencias:

```maude
load state.maude
load arithmetic_syntax.maude
load arithmetic_semantics.maude
load bool_syntax.maude
load bool_semantics.maude
load ns_while_syntax.maude
load ns_while_semantics.maude
```

Un programa se ejecuta mediante una reescritura sobre una configuración:

```maude
rew in NS-WHILE-SEMANTICS :
  < ('x := 2 ; 'y := 'x ** 3), empty > .
```

El resultado es el estado final equivalente a:

```maude
['x := 2] ['y := 6]
```

### Ejemplo: factorial

```maude
rew in NS-WHILE-SEMANTICS :
  < ('n := 5 ;
     'acc := 1 ;
     while ! ('n =? 0) do
       ('acc := 'acc ** 'n ;
        'n := 'n -- 1)),
    empty > .
```

El programa termina con `'n` igual a `0` y `'acc` igual a `120`.

## Objetivo académico

El proyecto muestra cómo una semántica operacional definida mediante reglas de inferencia puede transformarse en una especificación formal ejecutable. Esto permite experimentar con la semántica, validar programas y observar sus resultados directamente en Maude.

## Referencia

Hanne Riis Nielson y Flemming Nielson. *Semantics with Applications: A Formal Introduction*. Wiley, 1992.
