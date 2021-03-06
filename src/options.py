import random
import operator
import numpy as np
from pyflann import *
from operator import *
from itertools import *
from scipy.stats import mode
from rlglue.types import Action
from rlglue.types import Observation
from rlglue.agent.Agent import Agent
from rlglue.utils import TaskSpecVRLGLUE3
from pyrl.basis.fourier import FourierBasis
from rlglue.environment.Environment import Environment

class Option:
    """ A Markov option o consists of a tuple:
    :math:`langle \mathcal{I}, \pi, \beta \rangle`

    where the initiation set :math:`\mathcal{I}` specifies in which states the
    option can be invoked, :math:`\pi` is a sub-policy defined for
    o and :math:`\beta` defines the probability of terminating
    the execution of :math:`\pi` in any given state.

    The options framework was originally introduced in:

    R. S. Sutton, D. Precup, and S. Singh, "Between MDPs and semi-MDPs:
    A framework for temporal abstraction in reinforcement learning,"
    Artificial Intelligence, vol. 112, no. 1-2, pp. 181-211, 1999.

    """

    def initiate(self, observation):
        """ Initiation predicate

        :param observation: the current observation
        :returns: True if this option can be taken in the current observation
        :rtype: bool

        """

    def terminate(self, observation):
        """ Termination (beta) function

        :param observation: the current observation
        :returns: True if this option must terminate in the current observation
        :rtype: bool or float defined as a proper probability function

        """

    def pi(self, observation):
        """ A deterministic greedy policy with respect to the approximate
        action-value function. Please note that we generally don't want to
        learn a policy over non-stationary options. Exploration strategies over
        primitive actions are therefore not needed in this case.

        :param observation: the current observation
        :returns: the greedy action with respect to the action-value function of
        this option
        :rtype: int

        """
class PrimitiveOption(Option):
    """ This class wraps a primitive discrete action into an option.

    A primitive action can be seen as a special kind of option whose
    policy always selects it whenever it is available, can be initiated
    everwhere and only last one step.

    """

    def __init__(self, action):
        self.action = action

    def initiate(self, observation):
        return True

    def terminate(self, observation):
        return True

    def pi(self, observation):
        return self.action

    def __str__(self):
        return 'Primitive option %d'%(self.action,)

class KNNOption(Option):
    """ K-Nearest Neighbor Option

    Here we implement an option construction based on the community structures
    of a graph over continuous observations. A k-nearest neighbor index is used
    to control the initiation and termination conditions.

    More details can be found in:

    P. Bacon and D. Precup. "Using label propagation for learning
    temporally abstract actions in reinforcement learning." In Proceedings of
    the Workshop on Multiagent Interaction Networks (MAIN 2013), 2013.

    """
    def __init__(self, label, membership, index_filename, dataset_filename, nn=1):
        """ Create an option to reach the boundary

        :param label: The community label over which this option is defined
        :type label: int
        :param nn: The number of nearest neighbor for majority voting
        :type nn: int

        """
        self.nn = nn
        self.label = label
        self.membership = membership

        self.index = None
        self.index_filename = index_filename
        self.dataset_filename = dataset_filename
        self.initial_states = None

        self.basis = None
        self.weights = None

    def initial_state(self):
        return random.choice(self.initial_states)

    def initiate(self, observation):
        """ Initiation predicate

        The option can be initiated if the majority label among the
        nearest neighbors corresponds to the option's label.

        :param observation: the current observation
        :returns: True if this option can be taken under the current observation
        :rtype: bool

        """
        knn_idx, dists = self.index.nn_index(observation, num_neighbors=self.nn)
        return mode(self.membership[knn_idx[0]])[0][0] == self.label

    def terminate(self, observation):
        """ Termination (beta) function

        The definition of beta that we adopt here makes it either 0 or 1.
        It returns 1 whenever its closest neighbors belongs to a different community.

        :param observation: the current observation
        :returns: True if this option must terminate in the current observation
        :rtype: bool

        """
        return not self.initiate(observation)

    def pi(self, observation):
        """ A deterministic greedy policy with respect to the approximate
        action-value function. Please note that we generally don't want to
        learn a policy over non-stationary options. Exploration strategies over
        primitive actions are therefore not needed in this case.

        :param observation: the current observation
        :returns: the greedy action with respect to the action-value function of
        this option
        :rtype: int

        """
        return np.dot(self.weights.T, self.basis.computeFeatures(observation)).argmax()

    def __str__(self):
        return 'KNN option, community %d, nn %d'%(self.label, self.nn)

    def __getstate__(self):
        """ Implement pickling manually to avoid duplicating dataset

        """
        odict = self.__dict__.copy()
        del odict['index']
        del odict['initial_states']
        return odict

    def __setstate__(self, dict):
        """ Load the pickled object state

        The membership vector and index will have to be re-loaded manually.

        """
        self.__dict__.update(dict)

        self.index = FLANN()
        dataset = np.loadtxt(self.dataset_filename)
        self.index.load_index(self.index_filename, dataset)
        self.initial_states = dataset[self.membership == self.label]

class LogisticOption(Option):
    """ This type of option seeks to exit the subspace over which it's
    defined through the clustering procedure.

    A logistic classifier is learnt over the clusters in order to generalize
    to the continous state space.
    """

    def __init__(self, label, predictor, initial_states):
        """
        :param label: The community label over which this option is defined
        :type label: int
        :param predictor: A one-vs-all predictor
        :type predictor: sklearn.linear_model.LogisticRegression
        """
        self.label = label
        self.predictor = predictor
        self.initial_states = initial_states

        self.basis = None
        self.weights = None

    def initial_state(self):
        return random.choice(self.initial_states)

    def initiate(self, observation):
        """ Initiation predicate

        :param observation: the current observation
        :returns: True if predictor recognizes the observation as cluster member
        :rtype: bool

        """
        return self.predictor.predict(observation) == self.label

    def terminate(self, observation):
        """ Stochastic termination

        :param observation: the current observation
        :returns: True if the option must terminate
        :rtype: bool

        """
        labels_pr = self.predictor.predict_proba(observation)
        return random.random() > labels_pr[0,self.label]

    def pi(self, observation):
        """ A deterministic greedy policy with respect to the approximate
        action-value function. Please note that we generally don't want to
        learn a policy over non-stationary options. Exploration strategies over
        primitive actions are therefore not needed in this case.

        :param observation: the current observation
        :returns: the greedy action with respect to the action-value function of
        this option
        :rtype: int

        """
        return np.dot(self.weights.T, self.basis.computeFeatures(observation)).argmax()

class NavigationOption(KNNOption):
    """ K-Nearest Neighbor Option

    Here we implement an option construction based on the community structures
    of a graph over continuous observations. A k-nearest neighbor index is used
    to control the initiation and termination conditions.

    More details can be found in:

    P. Bacon and D. Precup. "Using label propagation for learning
    temporally abstract actions in reinforcement learning." In Proceedings of
    the Workshop on Multiagent Interaction Networks (MAIN 2013), 2013.

    """
    def __init__(self, source, target, membership, index_filename, dataset_filename, nn=1):
        """ Create an option to reach a particular target region

        :param source: The community label over which this option is defined
        :type source: int
        :param target: The target label associated with the community to reach
        :type target: int
        :param nn: The number of nearest neighbor for majority voting
        :type nn: int
        :param membership: The membership vector over all the vertices

        """
        self.target = target
        KNNOption.__init__(self, source, membership, index_filename, dataset_filename, nn)

    def terminate(self, observation):
        """ Termination (beta) function

        The definition of beta that we adopt here makes it either 0 or 1.
        It returns 1 whenever its closest neighbors belongs to a different community.

        :param observation: the current observation
        :returns: True if this option must terminate in the current observation
        :rtype: bool

        """
        knn_idx, dists = self.index.nn_index(observation, num_neighbors=self.nn)
        mode_label = mode(self.membership[knn_idx[0]])
        mode_freq = mode_label[1][0]
        mode_label = mode_label[0][0]

        return mode_label == self.target and mode_freq >= (self.nn/2)

    def __str__(self):
        return 'NavigationOption, from %d to %d, nn %d'%(self.label, self.target, self.nn)

class IntraOptionLearning(Agent):
    """ This class implements Intra-Option learning with
    linear function approximation.

    R. S. Sutton, D. Precup, and S. Singh, "Intra-option learning about
    temporally abstract actions," In Proceedings of the Fifteenth
    International Conference on Machine Learning (ICML 1998), 1998, pp. 556-564.

    """

    def __init__(self, options, alpha, gamma, epsilon, fa_order):
        """
        :param options: A set of options with learnt policies
        :type options: list of Option

        """
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.fa_order = fa_order
        self.options = options
        self.current_option = None
        self.finished_learning = False

    def intraoption_update(self, reward, features, observation):
        """ Perform a step of intra-option learning

        :param reward: The reward just obtained
        :param features: The features representation of the current state

        """

        for i in self.consistent_options(self.last_observation, self.last_action):
            current_value = 0.0
            if self.options[i].terminate(observation):
                initializable_options = self.initializable_options(observation)
                current_value = np.dot(self.weights[:,initializable_options].T, features).max()
            else:
                current_value = np.dot(self.weights[:,i].T, features)

            delta = reward + self.gamma*current_value - np.dot(self.weights[:,i].T, self.last_features)

            self.weights[:,i] += self.alpha*delta

    def consistent_options(self, observation, action):
        """
        :returns: a subset of the options for which pi_o(s) = a
        :rtype: list of int
        """
        return filter(lambda idx: self.options[idx].pi(observation) == action,
                        xrange(len(self.options)))


    def initializable_options(self, observation):
        """ Find the options available under the current state

        :retuns: The indices of the options that can be initiated under the current state
        :rtype: list of int

        """
        return filter(lambda idx: self.options[idx].initiate(observation), xrange(len(self.options)))

    def egreedy(self, observation, features):
        """ Use epsilon-greedy exploration for the behavior policy

        :param observation: The raw observations
        :param features: The features representation of the observation
        :returns: A random option with probability epsilon, or the option with
        the highest value with probability 1 - epsilon.
        :rtype: int

        """
        initializable_options = self.initializable_options(observation)

        if not self.finished_learning and (random.random() < self.epsilon):
            return random.choice(initializable_options)

        return initializable_options[np.dot(self.weights[:,initializable_options].T, features).argmax()]

    def mu(self, observation, features=None):
        """ The semi-markov deterministic policy that follows
        an option to completion before starting another one.

        :param observation: The raw observations
        :param features: The features representation of the observation
        :returns: the best option according to the current policy
        :rtype: Option

        """
        if self.current_option == None or self.current_option.terminate(observation):
            self.current_option = self.options[self.egreedy(observation, features)]

        return self.current_option

    def agent_init(self, taskspec):
        """ This function is called once at the begining of an episode.
        Performs sanity checks with the environment.

        :param taskspec: The task specifications
        :type taskspec: str

        """
        spec = TaskSpecVRLGLUE3.TaskSpecParser(taskspec)
        if len(spec.getIntActions()) != 1:
            raise Exception("Expecting 1-dimensional discrete actions")
        if len(spec.getDoubleActions()) != 0:
            raise Exception("Expecting no continuous actions")
        if spec.isSpecial(spec.getIntActions()[0][0]):
            raise Exception("Expecting min action to be a number not a special value")
        if spec.isSpecial(spec.getIntActions()[0][1]):
            raise Exception("Expecting max action to be a number not a special value")

        observation_ranges = spec.getDoubleObservations()
        self.basis = FourierBasis(len(observation_ranges), self.fa_order, observation_ranges)
        self.weights = np.zeros((self.basis.numTerms, len(self.options)))

        self.last_action = 0
        self.last_features = []
        self.last_observation = []

    def agent_start(self, obs):
        """ This function is called by the environment in the initial state.

        :param obs: An observation from the environment
        :rtype obs: :class:`rlglue.types.Observation`
        :returns: The primitive action to execute in the environment according to the
        behavior policy.
        :rtype: a primitive action under the form of a :class:`rlglue.types.Action`

        """
        observation = np.array(obs.doubleArray)
        current_features = self.basis.computeFeatures(observation)

        self.last_observation = observation
        self.last_features = current_features
        self.last_action = self.mu(observation, current_features).pi(observation)

        action = Action()
        action.intArray = [self.last_action]
        return action

    def agent_step(self, reward, obs):
        """ This function is called by the environment while the episode lasts.

        If learning is not frozen, the option-value function Q(s, o) is updated
        using intra-option learning.

        :param reward: The reward obtained as a result of the last transition.
        :param obs: An observation from the environment
        :rtype obs: :class:`rlglue.types.Observation`
        :returns: The primitive action to execute in the environment according to the
        behavior policy.
        :rtype: a primitive action under the form of a :class:`rlglue.types.Action`

        """
        observation = np.array(obs.doubleArray)
        current_features = self.basis.computeFeatures(observation)

        if not self.finished_learning:
            self.intraoption_update(reward, current_features, observation)

        self.last_observation = observation
        self.last_features = current_features
        self.last_action = self.mu(observation, current_features).pi(observation)

        action = Action()
        action.intArray = [self.last_action]
        return action

    def agent_end(self, reward):
        """ This function is called by the environment when the episode finishes.

        If learning is not frozen, the option-value function Q(s, o) is updated
        using intra-option learning.

        :param reward: The reward obtained as a result of the last transition.

        """
        if not self.finished_learning:
            for i in self.consistent_options(self.last_observation, self.last_action):
                delta = reward - np.dot(self.weights[:,i].T, self.last_features)
                self.weights[:,i] = self.weights[:,i] + self.alpha*delta

    def agent_cleanup(self):
        pass

    def agent_message(self, msg):
        return "Intra-Option Learning does not understand your message."

class PseudoRewardEnvironment(Environment):
    """ This class is a decorator for an RL-Glue environment.

    We need it to change at run time the terminal states of the
    underlying environment, and imposing our pseudo-reward function
    for the sake of learning a give policy for an option.

    """
    def __init__(self, decorated, option, subgoal_reward):
        """
        :param decorated: The base environment
        :type decorated: Environment
        :param option: The option over which to set up the pseudo-reward
        :type option: Option

        """
        self.decorated = decorated
        self.option = option
        self.subgoal_reward = subgoal_reward

    def env_step(self, action):
        returnRO = self.decorated.env_step(action)

        # Set pseudo-termination
        if self.option.terminate(np.asarray(returnRO.o.doubleArray)):
            returnRO.r += self.subgoal_reward
            returnRO.terminal = True

        return returnRO

    def env_init(self):
        return self.decorated.env_init()

    def env_start(self):
        return self.decorated.env_start()

    def env_cleanup(self):
        self.decorated.env_cleanup()

    def env_message(self, message):
        return self.decorated.env_message(message)

class TrajectoryRecorder(Environment):
    """ Records trajectories taken in the environment """

    def __init__(self, decorated, filename):
        """ This class provides a decorator wrapper to seamlessly record
        a trajectory taken in the environment.

        :param environment: an rlglue environment
        :type environment: Environment

        """
        self.decorated = decorated
        self.filename = filename
        self.trajectory_count = 0
        self.trajectory_file = None

    def env_init(self):
        return self.decorated.env_init()

    def env_start(self):
        if self.trajectory_file and not self.trajectory_file.closed:
            self.trajectory_file.close()
            self.trajectory_count += 1

        obs = self.decorated.env_start()
        self.trajectory_file = open('%s-%d.dat'%(self.filename, self.trajectory_count), 'wb')
        self.trajectory_file.write(' '.join(map(str, obs.doubleArray)) + '\n')
        self.trajectory_file.flush()

        return obs

    def env_step(self, action):
        returnRO = self.decorated.env_step(action)
        self.trajectory_file.write(' '.join(map(str, returnRO.o.doubleArray)) + '\n')
        self.trajectory_file.flush()

        if returnRO.terminal:
            self.trajectory_count += 1
            self.trajectory_file.close()

        return returnRO

    def env_cleanup(self):
        self.decorated.env_cleanup()

    def env_message(self, message):
        return self.decorated.env_message(message)
